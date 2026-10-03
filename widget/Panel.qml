import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Entry point for omarchy-screensaver-cadence.
//
// The root is a `Panel` and the bar button lives inside it. That is a hard
// requirement, not a style choice: the bar skips any slot whose activeItem does
// not expose open(), close() and opened, and only Ui.Panel provides those -- see
// the openSlots filter in shell/plugins/bar/Bar.qml. An earlier version rooted
// this file at BarWidget and pulled the panel in through a Loader with
// visible: false. The bar button rendered, but the panel never opened, and
// `omarchy-shell summon matthewh.cadence` could not find it either.
//
// Shows whether the screensaver is running, and offers the switches that are
// awkward by hand: start/stop, the notifications toggle, editing the config,
// previewing slides, and what the AI slides are currently saying.
//
// Every toggle goes through cadence-ctl.py, which writes state.json rather than
// editing cadence.yaml -- rewriting YAML with PyYAML would drop the user's
// comments. Nothing here writes the config directly.

Panel {
  id: root
  moduleName: "matthewh.cadence"
  ipcTarget: "matthewh.cadence"

  readonly property string helpers: (Quickshell.env("HOME") || "") + "/.config/omarchy/screensaver"
  readonly property string aiCache: (Quickshell.env("HOME") || "") + "/.cache/omarchy/cadence/ai"

  property int slides: 0
  property bool configured: false
  property bool running: false
  property bool notifications: false
  property int interval: 20

  // U+F1B6 play-circle when running, U+F03E image when idle. The original pair
  // was U+F0032 (an envelope) and U+F0003 (a cocktail glass) -- what you get
  // when codepoints are picked by sorting rather than by meaning. Written as
  // escapes on purpose: typed as literal characters these came out as U+F0136
  // and U+F003E, both undefined ranges, and rendered as a filled box.
  readonly property string glyph: running ? "\uF1B6" : "\uF03E"
  readonly property string tip: !configured
    ? "cadence: no config found"
    : (running
      ? "cadence: running \u2014 " + slides + " slide(s), click to stop"
      : "cadence: " + slides + " slide(s) every " + interval + "s \u2014 click to start")

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
  // `login` is only needed for the interactive actions. The status poll runs
  // cadence-ctl.py, which resolves everything from $HOME and shells out to
  // pgrep -- it never touches omarchy-shell, so a login shell there only
  // re-sourced .bash_profile every few seconds for nothing. The interactive
  // actions do need one: $EDITOR for edit-config, and ~/.local/bin on PATH for
  // the preview launcher.
  function sh(cmd, login) {
    Quickshell.execDetached(login ? ["bash", "-lc", cmd] : ["bash", "-c", cmd])
  }
  function ctl(args) {
    sh("python3 " + shellQuote(helpers + "/cadence-ctl.py") + " " + args + " >/dev/null 2>&1", true)
    poll.restart()
  }
  function shellQuote(s) {
    return "'" + String(s).replace(/'/g, "'\\''") + "'"
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

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyph
    active: root.running
    tooltipText: root.tip
    onPressed: function (b) {
      if (b === Qt.RightButton) {
        root.ctl("edit-config")
        return
      }
      root.toggle()
    }
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

  // The popup. KeyboardPanel is the shell's popup host: it needs an anchorItem to
  // position against, an explicit open binding, and a content size. Without it the
  // content is just loose children of an unsized Item -- which is why an earlier
  // version showed nothing on click, and an even earlier one painted a stray
  // surface into the bar.
  KeyboardPanel {
    id: popup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened

    PanelKeyCatcher {
      id: catcher
      anchors.fill: parent
      onMoveRequested: function (dx) { root.switchPanel(dx) }
      onCloseRequested: root.close()
      onTabRequested: function (direction) { root.switchPanel(direction) }
    }

    ColumnLayout {
      id: popupColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      spacing: Style.space(6)

  PanelSectionHeader {
    text: "Cadence"
  }

  // One dimmed line of state, rather than a panel tooltip plus per-row
  // subtitles all restating the same numbers.
  Text {
    Layout.leftMargin: Style.space(10)
    Layout.rightMargin: Style.space(10)
    Layout.bottomMargin: Style.space(4)
    textFormat: Text.PlainText
    text: !root.configured
      ? "No cadence.yaml found \u2014 right-click the bar icon to write one."
      : root.slides + " slide" + (root.slides === 1 ? "" : "s")
        + " \u00b7 " + root.interval + "s each \u00b7 " + (root.running ? "running" : "stopped")
    color: Qt.darker(root.bar.foreground, 1.5)
    font.family: root.bar.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  Button {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(10)
    Layout.rightMargin: Style.space(10)
    Layout.topMargin: Style.space(2)
    text: root.running ? "Stop" : "Start now"
    leftAlign: true
    foreground: root.bar.foreground
    fontFamily: root.bar.fontFamily
    onClicked: root.toggleScreensaver()
  }

  PanelSeparator {
    Layout.topMargin: Style.space(8)
    Layout.bottomMargin: Style.space(4)
  }

  // Notifications. CursorSurface supplies the hover fill and the single
  // highlight the shell uses for keyboard/mouse parity; ToggleSwitch is the real
  // switch. Both were hand-rolled before, which is why the rows had no hover
  // feedback and the switch needed a comment explaining itself.
  CursorSurface {
    id: notifyRow
    Layout.fillWidth: true
    foreground: root.bar.foreground
    implicitHeight: notifyLabel.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.ctl("set notifications_enabled " + (root.notifications ? "false" : "true"))
    }

    RowText {
      id: notifyLabel
      anchors.left: parent.left
      anchors.right: notifySwitch.left
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      title: "Notifications"
      subtitle: "Show the newest notification as a slide"
    }

    ToggleSwitch {
      id: notifySwitch
      anchors.right: parent.right
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      checked: root.notifications
      foreground: root.bar.foreground
      onToggled: {
        root.ctl("set notifications_enabled " + (root.notifications ? "false" : "true"))
        // Optimistic: reflect the press immediately, the poll confirms it.
        root.notifications = !root.notifications
      }
    }
  }



  // What the AI slides are currently saying. Read-only on purpose: the text is
  // generated, so anything typed here would be silently overwritten by the next
  // generation. Blank means nothing is cached -- though with the bundled defaults
  // seeded that should not happen, and print() falls back to them inline anyway.
  PanelSectionHeader {
    Layout.leftMargin: Style.space(10)
    Layout.topMargin: Style.space(10)
    text: "AI slides"
  }

  Column {
    Layout.fillWidth: true
    Layout.leftMargin: Style.space(10)
    Layout.rightMargin: Style.space(10)
    Layout.topMargin: Style.space(2)
    spacing: Style.space(6)

    Repeater {
      model: [
        { label: "haiku", body: root.aiHaiku },
        { label: "terse", body: root.aiTerse },
      ]

      Column {
        required property var modelData
        width: parent.width
        spacing: 0

        Text {
          width: parent.width
          text: modelData.label
          color: Qt.darker(root.bar.foreground, 1.5)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          text: modelData.body !== ""
            ? modelData.body
            : "nothing cached yet - this slide is skipped"
          color: modelData.body !== ""
            ? Util.alpha(root.bar.foreground, 0.75)
            : Qt.darker(root.bar.foreground, 1.9)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          maximumLineCount: 4
          elide: Text.ElideRight
        }
      }
    }
  }

  CursorSurface {
    id: editRow
    Layout.fillWidth: true
    foreground: root.bar.foreground
    implicitHeight: editLabel.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.ctl("edit-config")
    }

    RowText {
      id: editLabel
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      title: "Edit cadence.yaml"
      subtitle: root.configured ? "Slides, timing and groups" : "Not written yet"
    }
  }

  CursorSurface {
    id: previewRow
    Layout.fillWidth: true
    foreground: root.bar.foreground
    implicitHeight: previewLabel.implicitHeight + Style.spacing.rowPaddingX

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.sh(
        "omarchy-launch-floating-terminal-with-presentation "
          + shellQuote("bash -c 'omarchy-screensaver-cadence --dump | less -R'"), true)
    }

    RowText {
      id: previewLabel
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(10)
      anchors.verticalCenter: parent.verticalCenter
      title: "Preview slides"
      subtitle: "Prints every slide to a terminal"
    }
  }
    }

    contentWidth: popup.fittedContentWidth(Style.space(360))
    contentHeight: popup.fittedContentHeight(popupColumn.implicitHeight)
  }

  // Title + dimmed subtitle, the shape every row in the shell's panels uses.
  component RowText: Column {
    id: rowText
    property string title: ""
    property string subtitle: ""
    spacing: Style.space(1)

    Text {
      width: parent.width
      textFormat: Text.PlainText
      text: rowText.title
      color: rowText.parent.foreground
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.body
      elide: Text.ElideRight
    }

    Text {
      width: parent.width
      visible: rowText.subtitle !== ""
      textFormat: Text.PlainText
      text: rowText.subtitle
      color: Qt.darker(rowText.parent.foreground, 1.5)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideRight
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
