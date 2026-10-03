import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar widget for omarchy-screensaver-cadence.
//
// Shows whether the screensaver is running and offers the switches that are
// awkward to do by hand: start/stop, the notifications toggle, opening the
// config, and previewing the slides.
//
// Every toggle goes through cadence-ctl.py, which writes state.json rather than
// editing cadence.yaml -- rewriting YAML with PyYAML would drop the user's
// comments. Nothing here writes the config directly.

BarWidget {
  id: root
  moduleName: "matthewh.cadence"

  readonly property string helpers: (Quickshell.env("HOME") || "") + "/.config/omarchy/screensaver"

  property int slides: 0
  property bool configured: false
  property bool running: false
  property bool notifications: false
  property int interval: 20

  // U+F1B6 play-circle when running, U+F03E image when idle. The previous pair
  // was U+F0032 (an envelope) and U+F0003 (a cocktail glass) -- what you get
  // when codepoints are picked by sorting rather than by meaning.
  readonly property string glyph: running ? "󰄶" : "󰀾"
  readonly property string tip: !configured
    ? "cadence: no config found"
    : (running
      ? "cadence: running — " + slides + " slide(s), click to stop"
      : "cadence: " + slides + " slide(s) every " + interval + "s — click to start")

  // BarIconButton is the shell's own bar button: it handles sizing, theming,
  // the tooltip and left/right press. Hand-rolling a RowLayout here rendered at
  // zero width, because a MouseArea with Layout.fillWidth has nothing to fill.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Component.onCompleted: refresh()

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
      panel.toggle()
    }
  }

  Panel {
    id: panel
    moduleName: "matthewh.cadence"
    ipcTarget: "matthewh.cadence"

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
        ? "No cadence.yaml found — right-click the bar icon to write one."
        : root.slides + " slide" + (root.slides === 1 ? "" : "s")
          + " · " + root.interval + "s each · " + (root.running ? "running" : "stopped")
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
    // highlight the shell uses for keyboard/mouse parity; ToggleSwitch is the
    // real switch. Both were hand-rolled before, which is why the rows had no
    // hover feedback and the switch needed a comment explaining itself.
    CursorSurface {
      id: notifyRow
      Layout.fillWidth: true
      foreground: root.bar.foreground
      implicitHeight: notifyLabel.implicitHeight + Style.spacing.rowPaddingX

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          root.ctl("set notifications_enabled " + (root.notifications ? "false" : "true"))
          // Optimistic: reflect the press immediately, the poll confirms it.
          root.notifications = !root.notifications
        }
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
  }

  // Single poller. There used to be a second Timer living inside the panel
  // alongside this one, both at 4s, so every interval cost two login shells.
  Timer {
    id: poll
    interval: 4000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
}