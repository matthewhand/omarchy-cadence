import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar widget for omarchy-screensaver-cadence.
//
// Structure note, learned the hard way: this file is the plugin's `barWidget`
// entry point and its root is a `Panel`, with the `BarIconButton` as a direct
// child. Every first-party bar widget does it this way (omarchy.power,
// omarchy.bluetooth, omarchy.network, ...).
//
// The previous version wrapped a `Panel` inside a `BarWidget` and sized itself
// with `implicitWidth: button.implicitWidth`. That is not how the bar allocates
// slots, so the widget drew outside its own slot: it overlapped the neighbouring
// applets and left a stray surface over the clock. Deriving the width from the
// button's implicitWidth is the bug -- the Panel already occupies exactly one
// slot, and `anchors.fill: parent` on the button is all the sizing needed.
//
// Shows whether the screensaver is running and offers the switches that are
// awkward to do by hand: start/stop, the notifications toggle, opening the
// config, and previewing the slides.
//
// Every toggle goes through cadence-ctl.py, which writes state.json rather than
// editing cadence.yaml -- rewriting YAML with PyYAML would drop the user's
// comments. Nothing here writes the config directly.

Panel {
  id: root
  moduleName: "matthewh.cadence"
  ipcTarget: "matthewh.cadence"
  // The BarWidget entry owns the IpcHandler for this target, so the panel must
  // not register a second one -- Quickshell allows only one per target and logs
  // a warning if both try.
  manageIpc: false

  // Injected by BarWidget.qml via its Loader.
  property var hostWidget: null
  property var anchorItem: null

  readonly property string helpers: (Quickshell.env("HOME") || "") + "/.config/omarchy/screensaver"

  // Single source of truth is the host BarWidget; these mirror it so the content
  // can bind to plain names.
  readonly property int slides: hostWidget ? hostWidget.slides : 0
  readonly property bool configured: hostWidget ? hostWidget.configured : false
  readonly property bool running: hostWidget ? hostWidget.running : false
  readonly property bool notifications: hostWidget ? hostWidget.notifications : false
  readonly property int interval: hostWidget ? hostWidget.interval : 20

  // U+F1B6 play-circle when running, U+F03E image when idle. The previous pair
  // was U+F0032 (an envelope) and U+F0003 (a cocktail glass) -- what you get
  // when codepoints are picked by sorting rather than by meaning.
  readonly property string glyph: running ? "󰄶" : "󰀾"
  readonly property string tip: !configured
    ? "cadence: no config found"
    : (running
      ? "cadence: running — " + slides + " slide(s), click to stop"
      : "cadence: " + slides + " slide(s) every " + interval + "s — click to start")

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
    onClicked: hostToggle()
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
        // Optimistic update, the poll confirms it. It has to happen on the host:
        // `notifications` is a readonly mirror here, so assigning to it would
        // silently fail and the switch would not move until the next poll.
        if (root.hostWidget) root.hostWidget.toggleNotifications()
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
      onClicked: hostCtl("edit-config")
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
      onClicked: hostPreview()
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
}
