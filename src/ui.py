"""PyQt6 mixer UI for the OP-1 Field controller."""

import time

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QSlider, QDial, QFrame, QSizePolicy,
    QApplication, QComboBox, QSpinBox, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer, QPointF, QSize
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QPixmap, QPolygonF, QIcon

from src.controller import Controller, CC_VOLUME, CC_MUTE, CC_PAN
from src.automation import (
    AutomationEngine, Parameter, PARAMETER_LABELS,
    LfoWave, LfoClip, lfo_wave_value, LFO_WAVE_LABELS,
)

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


def _midi_to_ui(v: int) -> int:
    return round(v * 99 / 127)

def _ui_to_midi(v: int) -> int:
    return round(v * 127 / 99)

def _transport_icon(shape: str, color: str, size: int = 18) -> QIcon:
    """Draw a play triangle or stop square into a QIcon."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    if shape == "play":
        s = float(size)
        p.drawPolygon(QPolygonF([QPointF(1.0, 0.5), QPointF(s - 0.5, s / 2.0), QPointF(1.0, s - 0.5)]))
    else:  # stop
        m = 2
        p.drawRect(m, m, size - 2 * m, size - 2 * m)
    p.end()
    return QIcon(px)


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
# Pan dial with center reference marker
# ---------------------------------------------------------------------------

class PanDial(QDial):
    """QDial with a fixed dot at 12 o'clock: gray when off-center, accent when centered."""
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(_ACCENT) if self.value() == 64 else QColor(_DIM)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, 4.5), 3.0, 3.0)
        painter.end()


# ---------------------------------------------------------------------------
# Waveform preview widget
# ---------------------------------------------------------------------------

class WaveformPreview(QWidget):
    """Paints a live waveform curve for the selected LFO settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wave   = LfoWave.SINE
        self._depth  = 20
        self._center = 64
        self._phase  = 0.0
        self.setMinimumHeight(80)
        self.setMaximumHeight(80)

    def set_params(self, wave: LfoWave, depth: int, center: int) -> None:
        self._wave   = wave
        self._depth  = depth
        self._center = center
        self.update()

    def set_phase(self, phase: float) -> None:
        self._phase = phase
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin_y = 10

        p.fillRect(self.rect(), QColor(_BG))

        cy        = h / 2.0
        amplitude = h / 2.0 - margin_y

        # Center dashed line
        p.setPen(QPen(QColor("#3a3a3a"), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(0.0, cy), QPointF(float(w), cy))

        # Waveform — 2 cycles across the full width
        n_cycles = 2
        steps    = w * 2      # half-pixel resolution
        pen = QPen(QColor(_ACCENT), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)

        prev_pt = None
        for i in range(steps + 1):
            phase  = (i / steps) * n_cycles
            y_norm = lfo_wave_value(phase % 1.0, self._wave)
            px     = float(i) * w / steps
            py     = cy - y_norm * amplitude
            pt     = QPointF(px, py)
            if prev_pt is not None:
                p.drawLine(prev_pt, pt)
            prev_pt = pt

        # Playhead — position within first cycle
        phx = self._phase * (float(w) / n_cycles)
        p.setPen(QPen(QColor(_TEXT), 1, Qt.PenStyle.SolidLine))
        p.drawLine(QPointF(phx, 2.0), QPointF(phx, float(h) - 2.0))

        # Hi / lo value labels
        lo = max(0, self._center - self._depth)
        hi = min(127, self._center + self._depth)
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        p.setPen(QColor(_DIM))
        p.drawText(4, margin_y, str(_midi_to_ui(hi)))
        p.drawText(4, h - 2,    str(_midi_to_ui(lo)))

        p.end()


# ---------------------------------------------------------------------------
# Per-track strip — OP-1 Field style
# ---------------------------------------------------------------------------

class TrackStrip(QFrame):
    def __init__(self, track: int, controller: Controller, parent=None):
        super().__init__(parent)
        self._track = track
        self._ctrl  = controller
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

        # ── Header acts as mute toggle ──
        hf = QFont()
        hf.setPointSize(9)
        hf.setBold(True)
        hf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)

        self._mute_btn = QPushButton(f"TRACK  {self._track}")
        self._mute_btn.setFont(hf)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.clicked.connect(self._on_mute_clicked)
        self._set_mute_style(False)
        outer.addWidget(self._mute_btn)

        # ── Body ──
        body = QVBoxLayout()
        body.setSpacing(8)
        body.setContentsMargins(10, 12, 10, 12)

        # Pan knob (L / R flanking, no extra label)
        _side_style = f"color: {_DIM}; font-size: 10pt; font-weight: bold;"
        l_lbl = QLabel("L")
        l_lbl.setFixedWidth(18)
        l_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        l_lbl.setStyleSheet(_side_style)

        r_lbl = QLabel("R")
        r_lbl.setFixedWidth(18)
        r_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        r_lbl.setStyleSheet(_side_style)

        # Range 0–128: midpoint = 64 lands exactly at 12 o'clock
        self._pan_dial = PanDial()
        self._pan_dial.setRange(0, 128)
        self._pan_dial.setValue(64)
        self._pan_dial.setNotchesVisible(False)
        self._pan_dial.setWrapping(False)
        self._pan_dial.setFixedSize(64, 64)
        self._pan_dial.valueChanged.connect(self._on_pan_changed)

        pan_row = QHBoxLayout()
        pan_row.setContentsMargins(0, 0, 0, 0)
        pan_row.setSpacing(2)
        pan_row.addWidget(l_lbl)
        pan_row.addWidget(self._pan_dial, alignment=Qt.AlignmentFlag.AlignCenter)
        pan_row.addWidget(r_lbl)
        body.addLayout(pan_row)

        # Volume fader (no label; value shown below)
        self._vol_slider = QSlider(Qt.Orientation.Vertical)
        self._vol_slider.setRange(0, 127)
        self._vol_slider.setValue(100)
        self._vol_slider.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._vol_slider.setMinimumHeight(130)
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        body.addWidget(self._vol_slider, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._vol_val = QLabel(str(_midi_to_ui(100)))
        self._vol_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vol_val.setStyleSheet(f"color: {_DIM}; font-size: 10pt; font-weight: bold;")
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
        bg = "#111111" if muted else color
        fg = color     if muted else "#000000"
        self._mute_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {bg}; color: {fg};"
            f"  border-top-left-radius: 9px; border-top-right-radius: 9px;"
            f"  border-bottom-left-radius: 0; border-bottom-right-radius: 0;"
            f"  border: none;"
            f"}}"
        )

    def _on_pan_changed(self, value: int) -> None:
        cc = min(value, 127)   # dial range is 0–128; clamp top end for MIDI
        if self._ready:
            self._ctrl.set_pan(self._track, cc)

    def _on_volume_changed(self, value: int) -> None:
        self._vol_val.setText(str(_midi_to_ui(value)))
        if self._ready:
            self._ctrl.set_volume(self._track, value)

    # ------------------------------------------------------------------
    # External updates (automation + OP-1 → UI sync)
    # ------------------------------------------------------------------

    def current_midi_value(self, param: Parameter) -> int:
        if param is Parameter.VOLUME:
            return self._vol_slider.value()
        if param is Parameter.PAN:
            return min(self._pan_dial.value(), 127)
        if param is Parameter.MUTE:
            return 127 if self._ctrl.is_muted(self._track) else 0
        return 64

    def set_automation_value(self, param_name: str, value: int) -> None:
        """Move a control to reflect an automation value — no CC sent."""
        if param_name == Parameter.VOLUME.value:
            self._vol_slider.blockSignals(True)
            self._vol_slider.setValue(value)
            self._vol_slider.blockSignals(False)
            self._vol_val.setText(str(_midi_to_ui(value)))
        elif param_name == Parameter.PAN.value:
            self._pan_dial.blockSignals(True)
            self._pan_dial.setValue(value)
            self._pan_dial.blockSignals(False)
            self._pan_dial.update()
        elif param_name == Parameter.MUTE.value:
            muted = value >= 64
            self._ctrl.sync_mute_state(self._track, muted)
            self._mute_btn.blockSignals(True)
            self._mute_btn.setChecked(muted)
            self._mute_btn.blockSignals(False)
            self._set_mute_style(muted)

    def update_from_cc(self, control: int, value: int) -> None:
        """Sync UI from a CC message received from the OP-1 — no CC sent back."""
        if control == CC_VOLUME:
            self._vol_slider.blockSignals(True)
            self._vol_slider.setValue(value)
            self._vol_slider.blockSignals(False)
            self._vol_val.setText(str(_midi_to_ui(value)))
        elif control == CC_PAN:
            self._pan_dial.blockSignals(True)
            self._pan_dial.setValue(value)
            self._pan_dial.blockSignals(False)
            self._pan_dial.update()
        elif control == CC_MUTE:
            muted = value >= 64
            self._ctrl.sync_mute_state(self._track, muted)
            self._mute_btn.blockSignals(True)
            self._mute_btn.setChecked(muted)
            self._mute_btn.blockSignals(False)
            self._set_mute_style(muted)


# ---------------------------------------------------------------------------
# LFO modulator panel
# ---------------------------------------------------------------------------

class LfoPanel(QFrame):
    def __init__(self, engine: AutomationEngine, clock, get_value_fn, parent=None):
        super().__init__(parent)
        self._engine    = engine
        self._clock     = clock
        self._get_value = get_value_fn   # (track: int, param: Parameter) -> int
        self._active_lfos: list[LfoClip] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"LfoPanel {{ background-color: {_PANEL}; border-radius: 8px; border: 1px solid #2e2e2e; }}"
        )

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(14, 10, 14, 12)

        # Title
        title = QLabel("LFO MODULATOR")
        tf = QFont()
        tf.setPointSize(10)
        tf.setBold(True)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        title.setFont(tf)
        title.setStyleSheet(f"color: {_DIM};")
        root.addWidget(title)

        # Controls row: Track / Param / Wave selectors
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)
        self._track_combo = self._make_combo([str(t) for t in (1, 2, 3, 4)])
        self._param_combo = self._make_combo(list(PARAMETER_LABELS))
        self._wave_combo  = self._make_combo(list(LFO_WAVE_LABELS))
        for lbl_text, widget in [
            ("Track", self._track_combo),
            ("Param", self._param_combo),
            ("Wave",  self._wave_combo),
        ]:
            ctrl_row.addWidget(self._dim_label(lbl_text))
            ctrl_row.addWidget(widget)
        ctrl_row.addStretch()
        root.addLayout(ctrl_row)

        # Waveform preview
        self._preview = WaveformPreview()
        root.addWidget(self._preview)

        # Rate / Depth / Center row
        params_row = QHBoxLayout()
        params_row.setSpacing(6)

        self._rate_combo = self._make_combo(["1", "2", "4", "8", "16"])
        self._rate_combo.setCurrentText("4")

        self._depth_spin = QSpinBox()
        self._depth_spin.setRange(0, 63)
        self._depth_spin.setValue(20)
        self._depth_spin.setFixedWidth(52)
        self._depth_spin.setStyleSheet(f"color: {_TEXT}; background-color: {_BG}; font-size: 11pt;")

        self._center_spin = QSpinBox()
        self._center_spin.setRange(0, 127)
        self._center_spin.setValue(64)
        self._center_spin.setFixedWidth(52)
        self._center_spin.setStyleSheet(f"color: {_TEXT}; background-color: {_BG}; font-size: 11pt;")

        use_cur_btn = QPushButton("Use current")
        use_cur_btn.setFixedHeight(26)
        use_cur_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_MUTE_OFF}; color: {_TEXT};"
            f"  border: none; border-radius: 4px; font-size: 10pt; }}"
            f"QPushButton:hover {{ background-color: #3a3a3a; }}"
        )
        use_cur_btn.clicked.connect(self._on_use_current)

        params_row.addWidget(self._dim_label("Rate"))
        params_row.addWidget(self._rate_combo)
        params_row.addWidget(self._dim_label("b/cycle"))
        params_row.addSpacing(10)
        params_row.addWidget(self._dim_label("Depth ±"))
        params_row.addWidget(self._depth_spin)
        params_row.addSpacing(10)
        params_row.addWidget(self._dim_label("Center"))
        params_row.addWidget(self._center_spin)
        params_row.addSpacing(6)
        params_row.addWidget(use_cur_btn)
        params_row.addStretch()
        root.addLayout(params_row)

        # Action buttons
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        _btn_style = (
            lambda bg, bg2, fg="": (
                f"QPushButton {{ background-color: {bg}; color: {fg or _TEXT};"
                f"  border: none; border-radius: 4px; font-size: 11pt; }}"
                f"QPushButton:hover {{ background-color: {bg2}; }}"
            )
        )

        start_btn = QPushButton("▶  Start")
        start_btn.setFixedHeight(30)
        start_btn.setStyleSheet(_btn_style("#1e4a1e", "#2a6a2a"))
        start_btn.clicked.connect(self._on_start)

        stop_btn = QPushButton("✕  Stop Selected")
        stop_btn.setFixedHeight(30)
        stop_btn.setStyleSheet(_btn_style(_MUTE_OFF, "#3a3a3a"))
        stop_btn.clicked.connect(self._on_stop_selected)

        stop_all_btn = QPushButton("✕  Stop All")
        stop_all_btn.setFixedHeight(30)
        stop_all_btn.setStyleSheet(_btn_style(_MUTE_OFF, "#3a3a3a", _DIM))
        stop_all_btn.clicked.connect(self._on_stop_all)

        action_row.addWidget(start_btn)
        action_row.addWidget(stop_btn)
        action_row.addWidget(stop_all_btn)
        action_row.addStretch()
        root.addLayout(action_row)

        # Active LFO list
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("border: none; background-color: #333333; max-height: 1px;")
        root.addWidget(sep)

        root.addWidget(self._dim_label("Active LFOs"))

        self._lfo_list = QListWidget()
        self._lfo_list.setStyleSheet(
            f"QListWidget {{ background-color: {_BG}; color: {_TEXT};"
            f"  border: 1px solid #2e2e2e; border-radius: 4px; font-size: 10pt; }}"
        )
        self._lfo_list.setMaximumHeight(70)
        root.addWidget(self._lfo_list)

        # Live preview wiring
        self._wave_combo.currentTextChanged.connect(self._update_preview)
        self._depth_spin.valueChanged.connect(self._update_preview)
        self._center_spin.valueChanged.connect(self._update_preview)
        self._update_preview()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_combo(self, items: list[str]) -> QComboBox:
        box = QComboBox()
        box.addItems(items)
        box.setStyleSheet(
            f"QComboBox {{ font-size: 11pt; color: {_TEXT}; background-color: {_BG}; }}"
            f"QComboBox QAbstractItemView {{ color: {_TEXT}; background-color: {_BG};"
            f"  selection-background-color: {_ACCENT}; selection-color: #000; }}"
        )
        return box

    def _dim_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_DIM}; font-size: 10pt; font-weight: bold;")
        return lbl

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _update_preview(self, *_) -> None:
        wave   = LFO_WAVE_LABELS[self._wave_combo.currentText()]
        depth  = self._depth_spin.value()
        center = self._center_spin.value()
        self._preview.set_params(wave, depth, center)

    def _on_use_current(self) -> None:
        track = int(self._track_combo.currentText())
        param = PARAMETER_LABELS[self._param_combo.currentText()]
        self._center_spin.setValue(self._get_value(track, param))

    def _on_start(self) -> None:
        lfo = LfoClip(
            track        = int(self._track_combo.currentText()),
            parameter    = PARAMETER_LABELS[self._param_combo.currentText()],
            wave         = LFO_WAVE_LABELS[self._wave_combo.currentText()],
            rate_beats   = int(self._rate_combo.currentText()),
            depth        = self._depth_spin.value(),
            center_value = self._center_spin.value(),
        )
        self._engine.add_lfo(lfo)
        self._active_lfos.append(lfo)
        self._refresh_list()

    def _on_stop_selected(self) -> None:
        row = self._lfo_list.currentRow()
        if 0 <= row < len(self._active_lfos):
            lfo = self._active_lfos.pop(row)
            self._engine.remove_lfo(lfo)
            self._refresh_list()

    def _on_stop_all(self) -> None:
        self._engine.clear_lfos()
        self._active_lfos.clear()
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._lfo_list.clear()
        for lfo in self._active_lfos:
            lo = _midi_to_ui(max(0, lfo.center_value - lfo.depth))
            hi = _midi_to_ui(min(127, lfo.center_value + lfo.depth))
            self._lfo_list.addItem(QListWidgetItem(
                f"T{lfo.track}  {lfo.parameter.value.upper()[:3]}  "
                f"{lfo.wave.value}  {lo}↔{hi}  {lfo.rate_beats}b/cycle"
            ))

    def on_beat(self, beat_count: int) -> None:
        rate  = int(self._rate_combo.currentText())
        phase = ((beat_count - 1) % rate) / rate
        self._preview.set_phase(phase)


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
        self._controller = controller
        self._clock      = clock
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
        self.setMinimumSize(700, 560)
        self.setStyleSheet(f"QMainWindow {{ background-color: {_BG}; }}")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(14)
        root.setContentsMargins(18, 16, 18, 16)

        # Header
        header = QHBoxLayout()
        header.setSpacing(6)

        self._stop_btn = QPushButton()
        self._stop_btn.setIcon(_transport_icon("stop", _TEXT))
        self._stop_btn.setIconSize(QSize(16, 16))
        self._stop_btn.setFixedSize(48, 34)
        self._stop_btn.setToolTip("Stop")
        self._stop_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {_PANEL}; border: 1px solid #3a3a3a; border-radius: 7px;"
            f"}}"
            f"QPushButton:hover {{ background-color: #2a2a2a; }}"
            f"QPushButton:pressed {{ background-color: #111; }}"
        )
        self._stop_btn.clicked.connect(self._on_stop)
        header.addWidget(self._stop_btn)

        header.addStretch()

        self._bpm_label = QLabel("BPM: --")
        bf = QFont("Menlo", 20)
        bf.setBold(True)
        self._bpm_label.setFont(bf)
        self._bpm_label.setStyleSheet(f"color: {_ACCENT};")
        header.addWidget(self._bpm_label)
        root.addLayout(header)

        status = QLabel(f"● Connected: {port_name}")
        status.setStyleSheet(f"color: {_GREEN}; font-size: 11pt; font-weight: bold;")
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

        self._lfo_panel = LfoPanel(engine, self._clock, self._get_strip_value)
        root.addWidget(self._lfo_panel)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_beat(self, beat_num: int) -> None:
        self._last_beat_time = time.monotonic()
        bpm = self._clock.bpm
        if bpm is not None:
            self._bpm_label.setText(f"BPM: {bpm:.1f}")
        self._lfo_panel.on_beat(beat_num)

    def _on_automation_update(self, track: int, param_name: str, value: int) -> None:
        strip = self._strips.get(track)
        if strip:
            strip.set_automation_value(param_name, value)

    def _on_cc_received(self, channel: int, control: int, value: int) -> None:
        # mido channels are 0-indexed; channel 0 = track 1
        strip = self._strips.get(channel + 1)
        if strip:
            strip.update_from_cc(control, value)

    def _on_stop(self) -> None:
        self._controller.stop()

    def _get_strip_value(self, track: int, param: Parameter) -> int:
        strip = self._strips.get(track)
        return strip.current_midi_value(param) if strip else 64

    def _check_clock_loss(self) -> None:
        if (
            self._last_beat_time is not None
            and time.monotonic() - self._last_beat_time > 3.0
        ):
            self._bpm_label.setText("BPM: --")
            self._last_beat_time = None
