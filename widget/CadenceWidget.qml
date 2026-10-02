import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar widget for omarchy-screensaver-cadence.
//
// Shows how many slides are configured and whether the screensaver is running,
// and offers the switches that are awkward to do by hand: start/stop, the
// notifications toggle, opening the config, and the image folder.
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

  readonly property string glyph: running ? "󰐲" : "󰐃"
  readonly property string tip: !configured
    ? "cadence: no config found"
    : (running
      ? "cadence: running — " + slides + " slide(s), click to stop"
      : "cadence: " + slides + " slide(s) every " + interval + "s — click to start")

  visible: true

  // BarIconButton is the shell's own bar button: it handles sizing, theming,
  // the tooltip and left/right press. Hand-rolling a RowLayout here rendered at
  // zero width, because a MouseArea with Layout.fillWidth has nothing to fill.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Component.onCompleted: refresh()

  function sh(cmd) {
    // A login shell is required: omarchy-shell needs OMARCHY_PATH, which the bare
    // widget environment does not carry.
    Quickshell.execDetached(["bash", "-lc", cmd])
  }

  function ctl(args) {
    sh("python3 " + shellQuote(helpers + "/cadence-ctl.py") + " " + args + " >/dev/null 2>&1")
    poll.restart()
  }

  function shellQuote(s) {
    return "'" + String(s).replace(/'/g, "'\\''") + "'"
  }

  function toggleScreensaver() {
    if (root.running) {
      // Key off the window class, which is what both the launcher and the runner
      // use, so this stops the screensaver however it was started.
      sh("pkill -f '[o]rg.omarchy.screensaver' 2>/dev/null; pkill -x ttfx 2>/dev/null; true")
    } else {
      sh("omarchy-launch-screensaver-cadence force")
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
      panel.toggle()
    }
  }

  PanelToolTip {
    text: root.tip
  }

  Panel {
    id: panel
    moduleName: "matthewh.cadence"
    ipcTarget: "matthewh.cadence"

    PanelSectionHeader {
      text: "Cadence"
    }

    PanelToolTip {
      text: root.configured
        ? root.slides + " slide(s), " + root.interval + "s each — " + (root.running ? "running" : "stopped")
        : "No cadence.yaml found. Right-click the bar icon to edit it."
    }

    Rectangle {
      Layout.fillWidth: true
      implicitHeight: 46
      color: "transparent"
      radius: 6

      RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.space(2)
        anchors.rightMargin: Style.space(2)
        spacing: Style.spacing.md

        Text {
          text: root.running ? "Stop" : "Start now"
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          Layout.fillWidth: true
        }

        Text {
          text: root.running ? "■" : "▶"
          color: root.running ? Color.accent : Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }

      MouseArea {
        anchors.fill: parent
        onClicked: root.toggleScreensaver()
      }
    }

    Rectangle {
      Layout.fillWidth: true
      implicitHeight: 46
      color: "transparent"
      radius: 6

      RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.space(2)
        anchors.rightMargin: Style.space(2)
        spacing: Style.spacing.md

        ColumnLayout {
          spacing: 0
          Layout.fillWidth: true

          Text {
            text: "Notifications"
            color: Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.body
          }

          Text {
            text: "Show the newest notification as a slide"
            color: Util.alpha(Color.foreground, 0.5)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
          }
        }

        // Drawn rather than using ToggleSwitch so the on/off state is obvious at a
        // glance in the bar's dimmed palette.
        Rectangle {
          implicitWidth: Style.space(36)
          implicitHeight: Style.space(20)
          radius: height / 2
          color: root.notifications ? Color.accent : Style.normalFill
          border.color: root.notifications ? Color.accent : Style.normalBorderColor
          border.width: 1

          Rectangle {
            width: Style.space(16)
            height: width
            radius: width / 2
            y: (parent.height - height) / 2
            x: root.notifications ? parent.width - width - Style.space(2) : Style.space(2)
            color: root.notifications ? Color.accent : Util.alpha(Color.foreground, 0.5)
            Behavior on x {
              NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
            }
          }
        }
      }

      MouseArea {
        anchors.fill: parent
        onClicked: {
          root.ctl("set notifications_enabled " + (root.notifications ? "false" : "true"))
          // Optimistic: reflect the press immediately, the poll confirms it.
          root.notifications = !root.notifications
        }
      }
    }

    Rectangle {
      Layout.fillWidth: true
      implicitHeight: 46
      color: "transparent"
      radius: 6

      RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.space(2)
        anchors.rightMargin: Style.space(2)
        spacing: Style.spacing.md

        Text {
          text: "Edit cadence.yaml"
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          Layout.fillWidth: true
        }

        Text {
          text: "✎"
          color: Util.alpha(Color.foreground, 0.7)
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }

      MouseArea {
        anchors.fill: parent
        onClicked: root.ctl("edit-config")
      }
    }

    Rectangle {
      Layout.fillWidth: true
      implicitHeight: 46
      color: "transparent"
      radius: 6

      RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Style.space(2)
        anchors.rightMargin: Style.space(2)
        spacing: Style.spacing.md

        Text {
          text: "Preview slides"
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          Layout.fillWidth: true
        }

        Text {
          text: ">"
          color: Util.alpha(Color.foreground, 0.7)
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }
      }

        MouseArea {
          anchors.fill: parent
          // Prints every slide's art to a terminal instead of taking over the
          // screen, so a config change can be checked without a full screensaver.
          onClicked: root.sh("omarchy-launch-floating-terminal-with-presentation " + shellQuote("bash -c 'omarchy-screensaver-cadence --dump | less -R'"))
        }
    }

    Timer {
      id: statusTimer
      interval: 1000
      onTriggered: root.refresh()
    }

    Process {
      id: statusProc
      command: ["bash", "-lc", "python3 " + root.shellQuote(root.helpers + "/cadence-ctl.py") + " status"]
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

    Component.onCompleted: {
      statusTimer.interval = 4000
      statusTimer.triggeredOnStart = true
    }
  }

  Timer {
    id: poll
    interval: 4000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }
}