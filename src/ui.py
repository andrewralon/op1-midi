"""PyQt6 mixer UI for the OP-1 Field controller."""

import time

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QSlider, QDial, QFrame, QSizePolicy,
    QApplication, QComboBox, QSpinBox, QCheckBox, QListWidget,
    QListWidgetItem,
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor

from src.controller import Controller, CC_VOLUME, CC_MUTE, CC_PAN
from src.automation import AutomationEngine, Clip, Parameter, CURVE_LABELS, PARAMETER_LABELS

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
_BG       = "#111111"
_PANEL    = "#1e1e1e"
_ACCENT   = "#e8541a"
_MUTE_OFF = "#2a2a2a"
_TEXT     = "#d8d8d8"
_DIM      = "#aaaaaa"
_GREEN    = "#4ec94e"

# OP-1 Field per-track colors, matched from the device's mixer screen
TRACK_COLORS = {
    1: "#4477bb",   # steel blue
    2: "#bb9933",   # ochre / gold
    3: "#8899aa",   # blue-gray
    4: "#cc4422",   # brick orange-red
}


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = app.palette()
    p.setColor(p.ColorRole.Window,      QColor(_BG))
    p.setColor(p.ColorRole.WindowText,  QColor(_TEXT))
    p.setColor(p.ColorRole.Base,        QColor(_PANEL))
    p.setColor(p.ColorRole.Button,      QColor(_PANEL))
    p.setColor(p.ColorRole.ButtonText,  QColor(_TEXT))
    p.setColor(p.ColorRole.Highlight,   QColor(_ACCENT))
    app.setPalette(p)


# ---------------------------------------------------------------------------
# Cross-thread bridge
# ---------------------------------------------------------------------------

class ClockBridge(QObject):
    """
    Signals emitted from clock/automation daemon threads; Qt delivers them to
    the main thread via AutoConnection (queued cross-thread).
    Never touch widgets inside these emit calls — signals only.
    """
    beat             = pyqtSignal(int)        # every 24 MIDI ticks (one beat)
    automation_update = pyqtSignal(int, str, int)  # (track, param_name, value)
    cc_received      = pyqtSignal(int, int, int)   # (channel, control, value)


# ---------------------------------------------------------------------------
# Per-track strip — OP-1 Field style
# ---------------------------------------------------------------------------

class TrackStrip(QFrame):
    def __init__(self, track: int, controller: Controller, parent=None):
        super().__init__(parent)
        self._track = track
        self._ctrl = controller
        self._ready = False   # suppress CC sends during __init__ setup
        self._setup_ui()
        self._ready = True

    def _setup_ui(self) -> None:
        color = TRACK_COLORS[self._track]

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("TrackStrip")
        self.setStyleSheet(
            "QFrame#TrackStrip {"
            f"  background-color: {_PANEL};"
            "   border-radius: 10px;"
            f"  border: 1px solid #2e2e2e;"
            "}"
        )
        self.setFixedWidth(148)

        outer = QVBoxLayout(self)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        # ── Colored track header ──
        header = QFrame()
        header.setFixedHeight(30)
        header.setStyleSheet(
            f"background-color: {color};"
            "  border-radius: 9px 9px 0 0;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        t_lbl = QLabel(f"TRACK  {self._track}")
        hf = QFont()
        hf.setPointSize(8)
        hf.setBold(True)
        hf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        t_lbl.setFont(hf)
        t_lbl.setStyleSheet("color: #000000; background: transparent;")
        t_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(t_lbl)
        outer.addWidget(header)

        # ── Body ──
        body = QVBoxLayout()
        body.setSpacing(8)
        body.setContentsMargins(10, 12, 10, 12)

        # Mute — uses track color when active
        self._mute_btn = QPushButton("MUTE")
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFixedHeight(28)
        self._mute_btn.clicked.connect(self._on_mute_clicked)
        self._set_mute_style(False)
        body.addWidget(self._mute_btn)

        # Pan knob
        pan_lbl = QLabel("PAN")
        pan_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pan_lbl.setStyleSheet(f"color: {_DIM}; font-size: 8pt; font-weight: bold;")
        body.addWidget(pan_lbl)

        # Range 0–128 (not 0–127): midpoint = 64 lands exactly at 12 o'clock,
        # so the center notch tick is symmetric.  CC is clamped to 127 on send.
        self._pan_dial = QDial()
        self._pan_dial.setRange(0, 128)
        self._pan_dial.setValue(64)
        self._pan_dial.setNotchesVisible(True)
        self._pan_dial.setWrapping(False)
        self._pan_dial.setFixedSize(64, 64)
        self._pan_dial.valueChanged.connect(self._on_pan_changed)

        # Equal fixed-width L/R labels so the knob stays visually centred
        _side_style = f"color: {_DIM}; font-size: 8pt; font-weight: bold;"
        l_lbl = QLabel("L")
        l_lbl.setFixedWidth(18)
        l_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        l_lbl.setStyleSheet(_side_style)

        r_lbl = QLabel("R")
        r_lbl.setFixedWidth(18)
        r_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        r_lbl.setStyleSheet(_side_style)

        pan_row = QHBoxLayout()
        pan_row.setContentsMargins(0, 0, 0, 0)
        pan_row.setSpacing(2)
        pan_row.addWidget(l_lbl)
        pan_row.addWidget(self._pan_dial, alignment=Qt.AlignmentFlag.AlignCenter)
        pan_row.addWidget(r_lbl)
        body.addLayout(pan_row)

        self._pan_val = QLabel("C")
        self._pan_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pan_val.setStyleSheet(f"color: {_DIM}; font-size: 8pt; font-weight: bold;")
        body.addWidget(self._pan_val)

        # Volume fader
        vol_lbl = QLabel("VOLUME")
        vol_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vol_lbl.setStyleSheet(f"color: {_DIM}; font-size: 8pt; font-weight: bold;")
        body.addWidget(vol_lbl)

        # Qt vertical slider: min at bottom, max at top — correct fader orientation
        self._vol_slider = QSlider(Qt.Orientation.Vertical)
        self._vol_slider.setRange(0, 127)
        self._vol_slider.setValue(100)
        self._vol_slider.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._vol_slider.setMinimumHeight(130)
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        body.addWidget(self._vol_slider, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._vol_val = QLabel("100")
        self._vol_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vol_val.setStyleSheet(f"color: {_DIM}; font-size: 8pt; font-weight: bold;")
        body.addWidget(self._vol_val)

        outer.addLayout(body)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_mute_clicked(self, checked: bool) -> None:
        self._set_mute_style(checked)
        if checked:
            self._ctrl.mute(self._track)
        else:
            self._ctrl.unmute(self._track)

    def _set_mute_style(self, muted: bool) -> None:
        color = TRACK_COLORS[self._track]
        bg    = color    if muted else _MUTE_OFF
        fg    = "#000"   if muted else _TEXT
        self._mute_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {bg}; color: {fg};"
            f"  border: none; border-radius: 4px;"
            f"  font-weight: bold; font-size: 8pt; letter-spacing: 1px;"
            f"}}"
            f"QPushButton:hover {{ background-color: {color}; color: #000; }}"
        )

    def _on_pan_changed(self, value: int) -> None:
        cc = min(value, 127)   # dial range is 0–128; clamp top end for MIDI
        self._pan_val.setText(_pan_label(cc))
        if self._ready:
            self._ctrl.set_pan(self._track, cc)

    def _on_volume_changed(self, value: int) -> None:
        self._vol_val.setText(str(value))
        if self._ready:
            self._ctrl.set_volume(self._track, value)

    # ------------------------------------------------------------------
    # External updates (automation + OP-1 → UI sync)
    # ------------------------------------------------------------------

    def set_automation_value(self, param_name: str, value: int) -> None:
        """Move a control to reflect an automation value — no CC sent."""
        if param_name == Parameter.VOLUME.value:
            self._vol_slider.blockSignals(True)
            self._vol_slider.setValue(value)
            self._vol_slider.blockSignals(False)
            self._vol_val.setText(str(value))
        elif param_name == Parameter.PAN.value:
            self._pan_dial.blockSignals(True)
            self._pan_dial.setValue(value)
            self._pan_dial.blockSignals(False)
            self._pan_val.setText(_pan_label(value))

    def update_from_cc(self, control: int, value: int) -> None:
        """Sync UI from a CC message received from the OP-1 — no CC sent back."""
        if control == CC_VOLUME:
            self._vol_slider.blockSignals(True)
            self._vol_slider.setValue(value)
            self._vol_slider.blockSignals(False)
            self._vol_val.setText(str(value))
        elif control == CC_PAN:
            self._pan_dial.blockSignals(True)
            self._pan_dial.setValue(value)
            self._pan_dial.blockSignals(False)
            self._pan_val.setText(_pan_label(value))
        elif control == CC_MUTE:
            muted = value >= 64
            self._ctrl.sync_mute_state(self._track, muted)
            self._mute_btn.blockSignals(True)
            self._mute_btn.setChecked(muted)
            self._mute_btn.blockSignals(False)
            self._set_mute_style(muted)


def _pan_label(value: int) -> str:
    offset = value - 64
    return "C" if offset == 0 else f"{'L' if offset < 0 else 'R'}{abs(offset)}"


# ---------------------------------------------------------------------------
# Automation panel
# ---------------------------------------------------------------------------

class AutomationPanel(QFrame):
    def __init__(self, engine: AutomationEngine, clock, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._clock = clock
        self._clip_objects: list[Clip] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"AutomationPanel {{ background-color: {_PANEL}; border-radius: 8px; border: 1px solid #2e2e2e; }}"
        )

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(14, 10, 14, 12)

        title = QLabel("AUTOMATION")
        tf = QFont()
        tf.setPointSize(8)
        tf.setBold(True)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        title.setFont(tf)
        title.setStyleSheet(f"color: {_DIM};")
        root.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(16)

        form = QVBoxLayout()
        form.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        for lbl_text, widget in [
            ("Track", self._make_combo([str(t) for t in (1, 2, 3, 4)], "_track_box")),
            ("Param", self._make_combo(list(PARAMETER_LABELS), "_param_box")),
            ("Curve", self._make_combo(list(CURVE_LABELS), "_curve_box")),
        ]:
            row1.addWidget(self._dim_label(lbl_text))
            row1.addWidget(widget)
        form.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self._from_spin = self._make_spin(0, 127, 100, 52)
        self._to_spin   = self._make_spin(0, 127, 0,   52)
        self._dur_spin  = self._make_spin(1, 128, 8,   52)
        self._loop_chk  = QCheckBox("Loop")
        self._loop_chk.setStyleSheet(f"color: {_TEXT}; font-size: 9pt;")
        for lbl, w in [("From", self._from_spin), ("To", self._to_spin), ("Dur", self._dur_spin)]:
            row2.addWidget(self._dim_label(lbl))
            row2.addWidget(w)
        row2.addWidget(self._dim_label("beats"))
        row2.addSpacing(8)
        row2.addWidget(self._loop_chk)
        form.addLayout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        add_btn = QPushButton("▶  Add")
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(
            f"QPushButton {{ background-color: #1e4a1e; color: {_TEXT}; border: none; border-radius: 4px; font-size: 9pt; }}"
            f"QPushButton:hover {{ background-color: #2a6a2a; }}"
        )
        add_btn.clicked.connect(self._on_add)
        clr_btn = QPushButton("✕  Clear All")
        clr_btn.setFixedHeight(28)
        clr_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_MUTE_OFF}; color: {_TEXT}; border: none; border-radius: 4px; font-size: 9pt; }}"
            f"QPushButton:hover {{ background-color: #3a3a3a; }}"
        )
        clr_btn.clicked.connect(self._on_clear)
        row3.addWidget(add_btn)
        row3.addWidget(clr_btn)
        row3.addStretch()
        form.addLayout(row3)

        body.addLayout(form)

        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(self._dim_label("Active clips"))
        self._clip_list = QListWidget()
        self._clip_list.setStyleSheet(
            f"QListWidget {{ background-color: {_BG}; color: {_TEXT}; border: 1px solid #2e2e2e; border-radius: 4px; font-size: 8pt; }}"
        )
        self._clip_list.setMinimumWidth(200)
        self._clip_list.setMaximumHeight(90)
        right.addWidget(self._clip_list)
        body.addLayout(right)

        root.addLayout(body)

    def _make_combo(self, items: list[str], attr: str) -> QComboBox:
        box = QComboBox()
        box.addItems(items)
        box.setStyleSheet(f"font-size: 9pt; color: {_TEXT}; background-color: {_BG};")
        setattr(self, attr, box)
        return box

    def _make_spin(self, lo: int, hi: int, default: int, width: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(default)
        s.setFixedWidth(width)
        return s

    def _dim_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_DIM}; font-size: 8pt; font-weight: bold;")
        return lbl

    def _on_add(self) -> None:
        track    = int(self._track_box.currentText())
        param    = PARAMETER_LABELS[self._param_box.currentText()]
        curve    = CURVE_LABELS[self._curve_box.currentText()]
        from_val = self._from_spin.value()
        to_val   = self._to_spin.value()
        dur      = self._dur_spin.value()
        loop     = self._loop_chk.isChecked()
        start    = max(1, self._clock.beat_count + 1)

        clip = Clip(
            track=track, parameter=param, start_beat=start,
            duration_beats=dur, start_value=from_val, end_value=to_val,
            curve=curve, loop=loop,
        )
        self._engine.add(clip)
        self._clip_objects.append(clip)
        self._refresh_list()

    def _on_clear(self) -> None:
        self._engine.clear()
        self._clip_objects.clear()
        self._clip_list.clear()

    def refresh(self) -> None:
        active_ids = {id(c) for c in self._engine.clips}
        self._clip_objects = [c for c in self._clip_objects if id(c) in active_ids]
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._clip_list.clear()
        for clip in self._clip_objects:
            curve_name = next(k for k, v in CURVE_LABELS.items() if v is clip.curve)
            loop_tag = " ↻" if clip.loop else ""
            self._clip_list.addItem(QListWidgetItem(
                f"T{clip.track} {clip.parameter.value.upper()[:3]}  "
                f"{clip.start_value}→{clip.end_value}  "
                f"{clip.duration_beats}b  {curve_name}{loop_tag}"
            ))


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: Controller,
        clock,
        engine: AutomationEngine,
        bridge: ClockBridge,
        port_name: str,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._last_beat_time: float | None = None
        self._strips: dict[int, TrackStrip] = {}
        self._setup_ui(controller, engine, port_name)

        bridge.beat.connect(self._on_beat)
        bridge.automation_update.connect(self._on_automation_update)
        bridge.cc_received.connect(self._on_cc_received)

        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._check_clock_loss)
        self._watchdog.start(500)

    def _setup_ui(self, controller: Controller, engine: AutomationEngine, port_name: str) -> None:
        self.setWindowTitle("OP-1 Field MIDI Controller")
        self.setMinimumSize(700, 600)
        self.setStyleSheet(f"QMainWindow {{ background-color: {_BG}; }}")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(14)
        root.setContentsMargins(18, 16, 18, 16)

        # Header
        header = QHBoxLayout()
        title_lbl = QLabel("OP-1 Field MIDI Controller")
        tf = QFont()
        tf.setPointSize(15)
        tf.setBold(True)
        title_lbl.setFont(tf)
        title_lbl.setStyleSheet(f"color: {_TEXT};")
        header.addWidget(title_lbl)
        header.addStretch()
        self._bpm_label = QLabel("BPM: --")
        bf = QFont("Menlo", 20)
        bf.setBold(True)
        self._bpm_label.setFont(bf)
        self._bpm_label.setStyleSheet(f"color: {_ACCENT};")
        header.addWidget(self._bpm_label)
        root.addLayout(header)

        status = QLabel(f"● Connected: {port_name}")
        status.setStyleSheet(f"color: {_GREEN}; font-size: 9pt; font-weight: bold;")
        root.addWidget(status)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; background-color: #2a2a2a; max-height: 1px;")
        root.addWidget(sep)

        # Track strips
        tracks_row = QHBoxLayout()
        tracks_row.setSpacing(10)
        for t in (1, 2, 3, 4):
            strip = TrackStrip(t, controller)
            self._strips[t] = strip
            tracks_row.addWidget(strip)
        tracks_row.addStretch()
        root.addLayout(tracks_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("border: none; background-color: #2a2a2a; max-height: 1px;")
        root.addWidget(sep2)

        self._auto_panel = AutomationPanel(engine, self._clock)
        root.addWidget(self._auto_panel)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_beat(self, _beat_num: int) -> None:
        self._last_beat_time = time.monotonic()
        bpm = self._clock.bpm
        if bpm is not None:
            self._bpm_label.setText(f"BPM: {bpm:.1f}")
        self._auto_panel.refresh()

    def _on_automation_update(self, track: int, param_name: str, value: int) -> None:
        strip = self._strips.get(track)
        if strip:
            strip.set_automation_value(param_name, value)

    def _on_cc_received(self, channel: int, control: int, value: int) -> None:
        # mido channels are 0-indexed; channel 0 = track 1
        strip = self._strips.get(channel + 1)
        if strip:
            strip.update_from_cc(control, value)

    def _check_clock_loss(self) -> None:
        if (
            self._last_beat_time is not None
            and time.monotonic() - self._last_beat_time > 3.0
        ):
            self._bpm_label.setText("BPM: --")
            self._last_beat_time = None
