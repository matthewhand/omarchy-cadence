import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar entry point for omarchy-screensaver-cadence.
//
// Structure follows nixfred.rift, which is the shape that actually works for a
// third-party plugin:
//
//   * the entry file roots at `BarWidget` and owns the bar button
//   * the panel is loaded through a `Loader` with `visible: false`, so it never
//     paints into the bar
//   * the button's width is pinned with `fixedWidth: Style.bar.statusSlot`
//   * the IpcHandler lives here, and the panel sets `manageIpc: false`
//
// Two earlier attempts got this wrong and both showed up on screen. A version
// with the panel nested directly inside the `BarWidget` left a stray pale surface
// sitting over the neighbouring applets and the clock; sizing the widget with
// `implicitWidth: button.implicitWidth` instead of pinning the slot did the same
// thing. Rooting the file at `Panel` -- the first-party shape -- silently rendered
// no bar button at all for a third-party plugin. Hence the Loader and the
// explicit slot width.
//
// Status is polled here rather than in the panel, because the button's glyph and
// active state depend on it and the button lives on this side of the Loader.

BarWidget {
  id: root
  moduleName: "matthewh.cadence"

  readonly property string helpers: (Quickshell.env("HOME") || "") + "/.config/omarchy/screensaver"
  readonly property string aiCache: (Quickshell.env("HOME") || "") + "/.cache/omarchy/cadence/ai"

  // The AI slides' current text, read straight from the cache files.
  //
  // FileView rather than shelling out to `ai-slides.py status` on the poll: these
  // are small files that change a few times a day, so watching them costs
  // nothing, whereas a status call per tick would be another process every four
  // seconds. onFileChanged is what makes the field update by itself after a
  // regeneration, with no reload of the shell.
  property string aiHaiku: ""
  property string aiTerse: ""

  function refreshAi() {
    haikuView.reload()
    terseView.reload()
  }

  FileView {
    id: haikuView
    path: root.aiCache + "/haiku.txt"
    watchChanges: true
    onLoaded: root.aiHaiku = String(text() || "").trim()
    onFileChanged: reload()
  }

  FileView {
    id: terseView
    path: root.aiCache + "/terse.txt"
    watchChanges: true
    onLoaded: root.aiTerse = String(text() || "").trim()
    onFileChanged: reload()
  }

  property int slides: 0
  property bool configured: false
  property bool running: false
  property bool notifications: false
  property int interval: 20

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  // U+F1B6 play-circle when running, U+F03E image when idle. The original pair
  // was U+F0032 (an envelope) and U+F0003 (a cocktail glass) -- what you get
  // when codepoints are picked by sorting rather than by meaning.
  //
  // Written as escapes on purpose. Typed as literal characters they came out as
  // U+F0136 and U+F003E, which are in undefined ranges and rendered as a filled
  // box in the bar. Transcribing a glyph by hand is how that happened.
  readonly property string glyph: running ? "\uF1B6" : "\uF03E"
  readonly property string tip: !configured
    ? "cadence: no config found"
    : (running
      ? "cadence: running — " + slides + " slide(s), click to stop"
      : "cadence: " + slides + " slide(s) every " + interval + "s — click to start")

  // `login` is only needed for the interactive actions. The status poll runs
  // cadence-ctl.py, which resolves everything from $HOME and shells out to
  // pgrep -- it never touches omarchy-shell, so a login shell there only
  // re-sourced .bash_profile every few seconds for nothing. The interactive
  // actions do need one: $EDITOR for edit-config, and ~/.local/bin on PATH for
  // the preview launcher.
  function sh(cmd, login) {
    Quickshell.execDetached(login ? ["bash", "-lc", cmd] : ["bash", "-c", cmd])
  }

  function shellQuote(s) {
    return "'" + String(s).replace(/'/g, "'\\''") + "'"
  }

  function ctl(args) {
    sh("python3 " + shellQuote(helpers + "/cadence-ctl.py") + " " + args + " >/dev/null 2>&1", true)
    poll.restart()
  }

  function toggleNotifications() {
    ctl("set notifications_enabled " + (root.notifications ? "false" : "true"))
    root.notifications = !root.notifications
  }

  function toggleScreensaver() {
    if (root.running) {
      // Key off the window class, which is what both the launcher and the runner
      // use, so this stops the screensaver however it was started.
      sh("pkill -f '[o]rg.omarchy.screensaver' 2>/dev/null; pkill -x ttfx 2>/dev/null; true", true)
    } else {
      sh("omarchy-launch-screensaver-cadence force", true)
    }
    poll.restart()
  }

  function apply(data) {
    if (!data) return
    root.slides = Number(data.slides || 0)
    root.configured = !!data.configured
    root.running = !!data.running
    root.notifications = !!data.notifications
    root.interval = Number(data.interval || 20)
  }

  function refresh() {
    if (statusProc.running) return
    statusProc.running = true
  }

  function openPanel() { if (panelLoader.item) panelLoader.item.open() }
  function closePanel() { if (panelLoader.item) panelLoader.item.close() }
  function togglePanel() { if (panelLoader.item) panelLoader.item.toggle() }

  // Hand the panel the context it cannot reach on its own.
  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Component.onCompleted: refresh()

  // visible: false is load-bearing. Without it the loaded panel paints into the
  // bar slot instead of only into its own popup window.
  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  IpcHandler {
    target: "matthewh.cadence"
    function open(): void { root.openPanel() }
    function close(): void { root.closePanel() }
    function show(): void { root.openPanel() }
    function hide(): void { root.closePanel() }
    function toggle(): void { root.togglePanel() }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    fontSize: Style.font.icon
    // Pin the slot instead of trusting the button's own implicit width, which is
    // what made this widget overlap its neighbours.
    fixedWidth: root.vertical ? root.barSize : Style.bar.statusSlot
    active: root.running || root.opened
    tooltipText: root.tip
    onPressed: function (b) {
      if (b === Qt.RightButton) {
        root.ctl("edit-config")
        return
      }
      root.togglePanel()
    }
  }

  Process {
    id: statusProc
    command: ["bash", "-c", "python3 " + root.shellQuote(root.helpers + "/cadence-ctl.py") + " status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        const raw = String(text || "").trim()
        if (!raw) return
        try {
          const parsed = JSON.parse(raw)
          if (parsed && parsed.ok) root.apply(parsed.data)
        } catch (e) {
          // Malformed output is not worth surfacing: the next poll retries.
        }
      }
    }
  }

  // One poller. An earlier version had a second Timer inside the panel as well,
  // both at 4s, so every interval cost two login shells.
  Timer {
    id: poll
    interval: 4000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
}