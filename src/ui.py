"""PyQt6 mixer UI for the OP-1 Field controller."""

import logging
import math
import os
import time
from enum import Enum, auto

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QSlider, QDial, QFrame, QSizePolicy,
    QApplication, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox,
    QListWidget, QListWidgetItem, QCheckBox,
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QPointF, QSize, QTimer
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QPixmap, QIcon

from src.controller import Controller, CC_VOLUME, CC_MUTE, CC_PAN
from src.clock import PPQN
from src.automation import (
    AutomationEngine, Parameter, PARAMETER_LABELS,
    LfoWave, LfoClip, lfo_wave_value, LFO_WAVE_LABELS,
)

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
### UI ELEMENTS
_BG         = "#111111"
_PANEL      = "#1e1e1e"
_MUTE_OFF   = "#2a2a2a"
_ACCENT     = "#4ec94e"
_TEXT       = "#d8d8d8"
_DIM        = "#aaaaaa"
_BORDER     = "#2e2e2e"
_FADER      = "#888888"
_GROOVE     = "#333333"
_KNOB_RIM   = "#777777"
_HOVER      = "#3a3a3a"
### OP-1 PALETTE
_BLUE_1     = "#4477bb" # button 1
_OCHRE_2    = "#bb9933" # button 2
_GRAY_3     = "#848C94" # button 3
_ORANGE_4   = "#ff6a00" # button 4
### MORE COLORS
_BLACK      = "#000000"
_BLUESTEEL  = "#132542"
_GOLD       = "#fddf28"
_BLUEGRAY   = "#5c5c74"
_ORANGERED  = "#ff5349"
_GRAY       = "#555555"
_GREEN      = "#4ec94e"
_DARKGREEN  = "#1e4a1e"
_RED        = "#ff4444"

_CHECKMARK_SVG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "checkmark.svg").replace("\\", "/")

# OP-1 Field per-track colors, matched from the device's mixer screen
TRACK_COLORS = {
    1: _BLUE_1,    # steel blue
    2: _OCHRE_2,   # ochre
    3: _GRAY_3,    # blue gray
    4: _ORANGE_4,  # orange
}


# ---------------------------------------------------------------------------
# Tempo mode
# ---------------------------------------------------------------------------

class TempoMode(Enum):
    APP_CLOCK = auto()  # auto-detected: OP-1 silent (FREE or MIDI SYNC)
    OP1_CLOCK = auto()  # auto-detected: OP-1 sending clock (BEAT MATCH, PO SYNC, or 1/16)

_MODE_LABEL: dict[TempoMode, str] = {
    TempoMode.APP_CLOCK: "app (FREE or MIDI SYNC)",
    TempoMode.OP1_CLOCK: "op1 (BEAT MATCH or PO SYNC)",
}

_MANUAL_CYCLE: list[TempoMode] = [
    TempoMode.APP_CLOCK,
    TempoMode.OP1_CLOCK,
]


def _midi_to_ui(v: int) -> int:
    return round(v * 99 / 127)

def _ui_to_midi(v: int) -> int:
    return round(v * 127 / 99)


# Rate 1 (slowest) → 8 (fastest): ticks per LFO cycle
_RATE_TICKS: dict[int, int] = {
    1: 16 * PPQN,   # once per 16 beats
    2: 8  * PPQN,   # once per 8 beats
    3: 4  * PPQN,   # once per 4 beats
    4: 2  * PPQN,   # once per 2 beats
    5: PPQN,        # once per beat
    6: PPQN // 2,   # twice per beat
    7: PPQN // 4,   # 4× per beat
    8: PPQN // 8,   # 8× per beat
}

_RATE_DESC: dict[int, str] = {
    1: "1× / 16 beats",
    2: "1× / 8 beats",
    3: "1× / 4 beats",
    4: "1× / 2 beats",
    5: "1× / beat",
    6: "2× / beat",
    7: "4× / beat",
    8: "8× / beat",
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
    beat              = pyqtSignal(int)
    automation_update = pyqtSignal(int, str, int)
    cc_received       = pyqtSignal(int, int, int)


# ---------------------------------------------------------------------------
# Pan dial with center reference dot
# ---------------------------------------------------------------------------

class PanDial(QDial):
    """QDial drawn as a dark circle with a line indicator from center to rim."""
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        r = min(cx, cy) - 2.0

        # Knob body
        p.setPen(QPen(QColor(_KNOB_RIM), 1.0))
        p.setBrush(QColor(_GROOVE))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Indicator line: sweep -135° (min) to +135° (max) from 12 o'clock
        v = self.value()
        t = (v - self.minimum()) / max(1, self.maximum() - self.minimum())
        a = math.radians(-135.0 + t * 270.0)
        sa, ca = math.sin(a), math.cos(a)

        color = QColor(_ACCENT) if v == 64 else QColor(_TEXT)
        pen = QPen(color, 3.0 if v == 64 else 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(
            QPointF(cx + sa * 3.0,       cy - ca * 3.0),
            QPointF(cx + sa * (r - 3.0), cy - ca * (r - 3.0)),
        )

        p.end()


# ---------------------------------------------------------------------------
# Waveform preview widget
# ---------------------------------------------------------------------------

class WaveformPreview(QWidget):
    """Draws 2 cycles of the LFO waveform with an animated beat playhead."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wave       = LfoWave.SINE
        self._depth      = 20
        self._center     = 64
        self._phase      = 0.0
        self._rate_ticks = PPQN   # default: 1 cycle per beat
        self.setFixedHeight(65)
        self.setStyleSheet(
            f"background-color: {_BG};"
            f"border: 1px solid {_BORDER};"
            "border-radius: 4px;"
        )

    def set_params(self, wave: LfoWave, depth: int, center: int, rate_ticks: int = PPQN) -> None:
        self._wave       = wave
        self._depth      = depth
        self._center     = center
        self._rate_ticks = rate_ticks
        self.update()

    def set_phase(self, phase: float) -> None:
        self._phase = phase
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad = 8

        p.fillRect(self.rect(), QColor(_BG))

        cy        = h / 2.0
        amplitude = h / 2.0 - pad

        # Center dashed line
        _dash_pen = QPen(QColor(_KNOB_RIM), 1, Qt.PenStyle.CustomDashLine)
        _dash_pen.setDashPattern([4, 8])
        p.setPen(_dash_pen)
        p.drawLine(QPointF(0.0, cy), QPointF(float(w), cy))

        # Cycles visible = how many full cycles fit in one beat at this rate
        n_cycles = 8.0 * PPQN / self._rate_ticks   # 2 beats of content; e.g. 0.5 for rate 1, 16.0 for rate 8
        steps    = w * 2
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

        p.end()


# ---------------------------------------------------------------------------
# Per-track strip
# ---------------------------------------------------------------------------

class TrackStrip(QFrame):
    def __init__(self, track: int, controller: Controller, parent=None):
        super().__init__(parent)
        self._track = track
        self._ctrl  = controller
        self._ready = False
        self._setup_ui()
        self._ready = True

    def _setup_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("TrackStrip")
        self.setStyleSheet(
            "QFrame#TrackStrip {"
            f"  background-color: {_PANEL};"
            "   border-radius: 10px;"
            f"   border: 1px solid {_BORDER};"
            "}"
        )
        self.setFixedWidth(100)

        outer = QVBoxLayout(self)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        # Header = mute toggle button (just the track number)
        hf = QFont()
        hf.setPointSize(20)
        hf.setBold(True)

        self._mute_btn = QPushButton(f"{self._track}")
        self._mute_btn.setFont(hf)
        self._mute_btn.setCheckable(True)
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.clicked.connect(self._on_mute_clicked)
        self._set_mute_style(False)
        outer.addWidget(self._mute_btn)

        body = QVBoxLayout()
        body.setSpacing(8)
        body.setContentsMargins(6, 8, 6, 8)

        # Pan knob with L / R flanking labels
        _side = f"color: {_DIM}; font-size: 10pt; font-weight: bold;"
        l_lbl = QLabel("L")
        l_lbl.setFixedWidth(18)
        l_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        l_lbl.setStyleSheet(_side)
        r_lbl = QLabel("R")
        r_lbl.setFixedWidth(18)
        r_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        r_lbl.setStyleSheet(_side)

        self._pan_dial = PanDial()
        self._pan_dial.setRange(0, 128)
        self._pan_dial.setValue(64)
        self._pan_dial.setNotchesVisible(False)
        self._pan_dial.setWrapping(False)
        self._pan_dial.setFixedSize(44, 44)
        self._pan_dial.valueChanged.connect(self._on_pan_changed)

        pan_row = QHBoxLayout()
        pan_row.setContentsMargins(0, 0, 0, 0)
        pan_row.setSpacing(2)
        pan_row.addWidget(l_lbl)
        pan_row.addWidget(self._pan_dial, alignment=Qt.AlignmentFlag.AlignCenter)
        pan_row.addWidget(r_lbl)
        body.addLayout(pan_row)

        # Volume fader (left) + value (right), vertically centered
        fader_row = QHBoxLayout()
        fader_row.setSpacing(6)
        fader_row.setContentsMargins(0, 0, 0, 0)

        self._vol_slider = QSlider(Qt.Orientation.Vertical)
        self._vol_slider.setRange(0, 127)
        self._vol_slider.setValue(115)
        self._vol_slider.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._vol_slider.setMinimumHeight(110)
        self._vol_slider.setFixedWidth(28)
        self._vol_slider.setStyleSheet(
            "QSlider::groove:vertical {"
            f"  width: 4px; background-color: {_GROOVE}; border-radius: 2px;"
            "}"
            "QSlider::sub-page:vertical {"
            f"  background-color: {_GRAY}; border-radius: 2px; width: 4px;"
            "}"
            "QSlider::add-page:vertical {"
            f"  background-color: {_RED}; border-radius: 2px; width: 4px;"
            "}"
            "QSlider::handle:vertical {"
            f"  background-color: {_FADER}; border: none;"
            "  width: 28px; height: 10px;"
            "  margin: 0 -12px; border-radius: 3px;"
            "}"
        )
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        fader_row.addSpacing(10)
        fader_row.addWidget(self._vol_slider)

        self._vol_val = QLabel(str(_midi_to_ui(115)))
        self._vol_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vol_val.setStyleSheet(f"color: {_TEXT}; font-size: 20pt; font-weight: bold;")
        fader_row.addWidget(self._vol_val, alignment=Qt.AlignmentFlag.AlignVCenter)

        body.addLayout(fader_row)

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
        bg = _BG    if muted else color
        fg = color  if muted else _BLACK
        self._mute_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {bg}; color: {fg};"
            f"  border-top-left-radius: 9px; border-top-right-radius: 9px;"
            f"  border-bottom-left-radius: 0; border-bottom-right-radius: 0;"
            f"  border: none;"
            f"}}"
        )

    def _on_pan_changed(self, value: int) -> None:
        cc = min(value, 127)
        if self._ready:
            self._ctrl.set_pan(self._track, cc)

    def _on_volume_changed(self, value: int) -> None:
        self._vol_val.setText(str(_midi_to_ui(value)))
        if self._ready:
            self._ctrl.set_volume(self._track, value)

    # ------------------------------------------------------------------
    # External updates
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
        """Update a control from automation — does not re-send CC."""
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
        """Sync UI from OP-1 CC — does not re-send CC."""
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
        self._engine      = engine
        self._clock       = clock
        self._get_value   = get_value_fn
        self._active_lfos: list[LfoClip] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"LfoPanel {{ background-color: {_PANEL}; border-radius: 8px;"
            f"  border: 1px solid {_BORDER}; }}"
        )

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(14, 10, 14, 10)

        # ── Row 1: title + Track buttons / Param / Wave ──
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        title = QLabel("LFO")
        tf = QFont()
        tf.setPointSize(14)
        tf.setBold(True)
        tf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        title.setFont(tf)
        title.setStyleSheet(f"color: {_DIM};")
        hdr.addWidget(title)

        hdr.addSpacing(8)

        # Track toggle buttons — create before wiring signals to avoid premature callbacks
        hdr.addWidget(self._dim_label("Tracks"))
        self._track_btns: dict[int, QPushButton] = {}
        for t in (1, 2, 3, 4):
            btn = QPushButton(str(t))
            btn.setCheckable(True)
            btn.setChecked(t == 1)
            btn.setFixedSize(28, 28)
            self._track_btns[t] = btn
            hdr.addWidget(btn)

        hdr.addSpacing(16)
        self._param_combo = self._make_combo(list(PARAMETER_LABELS))
        self._wave_combo  = self._make_combo(list(LFO_WAVE_LABELS))

        hdr.addWidget(self._dim_label("Param"))
        hdr.addWidget(self._param_combo)
        hdr.addSpacing(16)
        hdr.addWidget(self._dim_label("Wave"))
        hdr.addWidget(self._wave_combo)

        hdr.addStretch()
        self._invert_check = QCheckBox("Invert 2nd+")
        self._invert_check.setStyleSheet(
            f"QCheckBox {{ color: {_TEXT}; font-size: 12pt; }}"
            f"QCheckBox::indicator {{ border: 1px solid {_KNOB_RIM}; border-radius: 3px;"
            f"  background-color: {_PANEL}; width: 13px; height: 13px; }}"
            f"QCheckBox::indicator:checked {{ background-color: {_PANEL}; border-color: {_KNOB_RIM}; image: url({_CHECKMARK_SVG}); }}"
        )
        hdr.addWidget(self._invert_check)

        hdr.addStretch()
        root.addLayout(hdr)

        # Wire track buttons and set initial styles now that invert_check exists
        for btn in self._track_btns.values():
            btn.toggled.connect(lambda _: self._update_track_btn_styles())
        self._update_track_btn_styles()

        # ── Row 2: waveform preview ──
        self._preview = WaveformPreview()
        root.addWidget(self._preview)

        self._range_label = QLabel()
        self._range_label.setStyleSheet(f"color: {_DIM}; font-size: 12pt;")
        self._range_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # ── Row 3: Rate / Depth / Center ──
        params_row = QHBoxLayout()
        params_row.setSpacing(6)

        _spin_style = f"color: {_TEXT}; background-color: {_BG}; font-size: 11pt;"

        self._rate_spin = QSpinBox()
        self._rate_spin.setRange(1, 8)
        self._rate_spin.setValue(3)   # default: 4 beats/cycle
        self._rate_spin.setFixedWidth(44)
        self._rate_spin.setStyleSheet(_spin_style)

        self._rate_desc_lbl = QLabel(_RATE_DESC[3])
        self._rate_desc_lbl.setStyleSheet(f"color: {_DIM}; font-size: 11pt;")
        self._rate_spin.valueChanged.connect(
            lambda v: self._rate_desc_lbl.setText(_RATE_DESC[v])
        )
        self._rate_spin.valueChanged.connect(lambda _: self._update_preview())

        self._depth_spin = QSpinBox()
        self._depth_spin.setRange(0, 49)
        self._depth_spin.setValue(25)
        self._depth_spin.setFixedWidth(52)
        self._depth_spin.setStyleSheet(_spin_style)

        self._center_spin = QSpinBox()
        self._center_spin.setRange(0, 99)
        self._center_spin.setValue(50)  # ≈ MIDI 64 (center)
        self._center_spin.setFixedWidth(52)
        self._center_spin.setStyleSheet(_spin_style)

        use_cur_btn = QPushButton("Use current")
        use_cur_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_HOVER}; color: {_TEXT};"
            f"  border: none; border-radius: 4px; font-size: 12pt;"
            f"  padding: 4px 14px; }}"
            f"QPushButton:hover {{ background-color: {_KNOB_RIM}; }}"
        )
        use_cur_btn.clicked.connect(self._on_use_current)

        params_row.addWidget(self._dim_label("Rate"))
        params_row.addWidget(self._rate_spin)
        params_row.addWidget(self._rate_desc_lbl)
        params_row.addSpacing(12)
        params_row.addWidget(self._dim_label("Depth ±"))
        params_row.addWidget(self._depth_spin)
        params_row.addSpacing(12)
        params_row.addWidget(self._dim_label("Center"))
        params_row.addWidget(self._center_spin)
        params_row.addSpacing(6)
        params_row.addWidget(use_cur_btn)
        params_row.addStretch()
        params_row.addWidget(self._range_label)
        root.addLayout(params_row)

        # ── Rows 5+6: action buttons (left) + Active LFOs (right) ──
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)
        bottom_row.setContentsMargins(0, 0, 0, 0)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        btn_col.setContentsMargins(0, 0, 0, 0)

        start_btn = QPushButton("▶  Start")
        start_btn.setFixedHeight(28)
        start_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_DARKGREEN}; color: {_TEXT};"
            f"  border: none; border-radius: 4px; font-size: 11pt; padding: 0px 14px; }}"
            f"QPushButton:hover {{ background-color: #2a6a2a; }}"
        )
        start_btn.clicked.connect(self._on_start)

        stop_btn = QPushButton("■  Stop")
        stop_btn.setFixedHeight(28)
        stop_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_HOVER}; color: {_TEXT};"
            f"  border: none; border-radius: 4px; font-size: 11pt; padding: 0px 14px; }}"
            f"QPushButton:hover {{ background-color: {_KNOB_RIM}; }}"
        )
        stop_btn.clicked.connect(self._on_stop_selected)

        clear_btn = QPushButton("✕  Clear")
        clear_btn.setFixedHeight(28)
        clear_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_HOVER}; color: {_TEXT};"
            f"  border: none; border-radius: 4px; font-size: 11pt; padding: 0px 14px; }}"
            f"QPushButton:hover {{ background-color: {_KNOB_RIM}; }}"
        )
        clear_btn.clicked.connect(self._on_stop_all)

        btn_col.addWidget(start_btn)
        btn_col.addWidget(stop_btn)
        btn_col.addWidget(clear_btn)

        lfo_col = QVBoxLayout()
        lfo_col.setSpacing(4)
        lfo_col.setContentsMargins(0, 0, 0, 0)
        lfo_col.addWidget(self._dim_label("Active LFOs"))

        self._lfo_list = QListWidget()
        self._lfo_list.setStyleSheet(
            f"QListWidget {{ background-color: {_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 4px; font-size: 10pt; }}"
        )
        self._lfo_list.setFixedHeight(72)
        lfo_col.addWidget(self._lfo_list)

        bottom_row.addLayout(btn_col)
        bottom_row.addLayout(lfo_col, stretch=1)
        root.addLayout(bottom_row)

        # Wire up live preview
        self._wave_combo.currentTextChanged.connect(self._update_preview)
        self._depth_spin.valueChanged.connect(self._update_preview)
        self._center_spin.valueChanged.connect(self._update_preview)
        self._update_preview()

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
        lbl.setStyleSheet(f"color: {_DIM}; font-size: 12pt; font-weight: bold;")
        return lbl

    def _update_track_btn_styles(self) -> None:
        selected_count = sum(1 for btn in self._track_btns.values() if btn.isChecked())
        for t, btn in self._track_btns.items():
            color = TRACK_COLORS[t]
            if btn.isChecked():
                style = (
                    f"QPushButton {{ background-color: {color}; color: {_BLACK};"
                    f"  border: none; border-radius: 4px; font-size: 14pt; font-weight: bold; }}"
                    f"QPushButton:hover {{ background-color: {color}; }}"
                )
            else:
                style = (
                    f"QPushButton {{ background-color: {_HOVER}; color: {_TEXT};"
                    f"  border: none; border-radius: 4px; font-size: 14pt; font-weight: bold; }}"
                    f"QPushButton:hover {{ background-color: {_KNOB_RIM}; }}"
                )
            btn.setStyleSheet(style)

    def _update_preview(self, *_) -> None:
        wave        = LFO_WAVE_LABELS[self._wave_combo.currentText()]
        depth_midi  = _ui_to_midi(self._depth_spin.value())
        center_midi = _ui_to_midi(self._center_spin.value())
        rate_ticks  = _RATE_TICKS[self._rate_spin.value()]
        self._preview.set_params(wave, depth_midi, center_midi, rate_ticks)
        lo = _midi_to_ui(max(0,   center_midi - depth_midi))
        hi = _midi_to_ui(min(127, center_midi + depth_midi))
        self._range_label.setText(f"Range: {lo} – {hi}")

    def _on_use_current(self) -> None:
        selected = [t for t, btn in self._track_btns.items() if btn.isChecked()]
        if not selected:
            return
        param    = PARAMETER_LABELS[self._param_combo.currentText()]
        midi_val = self._get_value(selected[0], param)
        self._center_spin.setValue(_midi_to_ui(midi_val))

    def _on_start(self) -> None:
        selected = [t for t, btn in self._track_btns.items() if btn.isChecked()]
        if not selected:
            return
        param            = PARAMETER_LABELS[self._param_combo.currentText()]
        wave             = LFO_WAVE_LABELS[self._wave_combo.currentText()]
        rate_ticks       = _RATE_TICKS[self._rate_spin.value()]
        depth            = _ui_to_midi(self._depth_spin.value())
        center_value     = _ui_to_midi(self._center_spin.value())
        invert_secondary = self._invert_check.isChecked()
        for i, track in enumerate(selected):
            lfo = LfoClip(
                track        = track,
                parameter    = param,
                wave         = wave,
                rate_ticks   = rate_ticks,
                depth        = depth,
                center_value = center_value,
                inverted     = invert_secondary and i > 0,
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
            lo = _midi_to_ui(max(0,   lfo.center_value - lfo.depth))
            hi = _midi_to_ui(min(127, lfo.center_value + lfo.depth))
            if lfo.rate_ticks >= PPQN:
                rate_str = f"{lfo.rate_ticks // PPQN}b/cycle"
            else:
                rate_str = f"{PPQN // lfo.rate_ticks}×/beat"
            inv_str = " [inv]" if lfo.inverted else ""
            self._lfo_list.addItem(QListWidgetItem(
                f"T{lfo.track}  {lfo.parameter.value.upper()[:3]}  "
                f"{lfo.wave.value}  {lo}↔{hi}  {rate_str}{inv_str}"
            ))

    def on_beat(self, beat_count: int) -> None:
        rate_ticks  = _RATE_TICKS[self._rate_spin.value()]
        beat_ticks  = (beat_count - 1) * PPQN
        phase       = (beat_ticks % rate_ticks) / rate_ticks
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
        clock_gen,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._clock      = clock
        self._clock_gen  = clock_gen
        self._strips: dict[int, TrackStrip] = {}
        self._setup_ui(controller, engine, port_name, clock_gen)

        bridge.beat.connect(self._on_beat)
        bridge.automation_update.connect(self._on_automation_update)
        bridge.cc_received.connect(self._on_cc_received)

    def _setup_ui(self, controller: Controller, engine: AutomationEngine, port_name: str, clock_gen) -> None:
        self.setWindowTitle("OP-1 LFO Hero")
        self.setMinimumSize(700, 600)
        self.setStyleSheet(f"QMainWindow {{ background-color: {_BG}; }}")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(12)
        root.setContentsMargins(18, 14, 18, 14)

        # ── Transport + octave buttons (left of tracks) ──
        _btn_ss = (
            f"QPushButton {{ background-color: {_MUTE_OFF}; color: {_TEXT};"
            f"  border: none; border-radius: 5px; font-size: 14pt; }}"
            f"QPushButton:hover {{ background-color: {_HOVER}; }}"
            f"QPushButton:pressed {{ background-color: #4a4a4a; }}"
        )

        def _make_btn(label: str) -> QPushButton:
            b = QPushButton(label)
            b.setFixedSize(38, 32)
            b.setStyleSheet(_btn_ss)
            return b

        play_btn     = _make_btn("▶")
        stop_btn     = _make_btn("■")
        oct_left_btn = _make_btn("←")
        oct_right_btn = _make_btn("→")

        play_btn.clicked.connect(clock_gen.play)
        stop_btn.clicked.connect(clock_gen.stop)
        oct_left_btn.clicked.connect(clock_gen.tape_prev_bar)
        oct_right_btn.clicked.connect(clock_gen.tape_next_bar)

        transport_row = QHBoxLayout()
        transport_row.setSpacing(4)
        transport_row.addWidget(play_btn)
        transport_row.addWidget(stop_btn)

        octave_row = QHBoxLayout()
        octave_row.setSpacing(4)
        octave_row.addWidget(oct_left_btn)
        octave_row.addWidget(oct_right_btn)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        btn_col.addStretch()
        btn_col.addLayout(transport_row)
        btn_col.addLayout(octave_row)
        btn_col.addStretch()

        # ── Track strips, centered as a group with button column ──
        tracks_row = QHBoxLayout()
        tracks_row.setSpacing(10)
        tracks_row.addStretch()
        tracks_row.addLayout(btn_col)
        for t in (1, 2, 3, 4):
            strip = TrackStrip(t, controller)
            self._strips[t] = strip
            tracks_row.addWidget(strip)

        bpm_widget = QWidget()
        bpm_widget.setFixedWidth(130)
        bpm_layout = QVBoxLayout(bpm_widget)
        bpm_layout.setSpacing(1)
        bpm_layout.setContentsMargins(2, 0, 2, 0)
        bpm_layout.addStretch()

        bpm_title = QLabel("BPM")
        bpm_title.setStyleSheet(f"color: {_DIM}; font-size: 14pt; font-weight: bold;")
        bpm_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bpm_layout.addWidget(bpm_title)

        self._bpm_spin = QDoubleSpinBox()
        self._bpm_spin.setRange(20.0, 300.0)
        self._bpm_spin.setDecimals(1)
        self._bpm_spin.setSingleStep(1.0)
        self._bpm_spin.setValue(100.0)
        self._bpm_spin.setFixedWidth(66)
        self._bpm_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._bpm_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._bpm_spin.setStyleSheet(
            f"QDoubleSpinBox {{ color: {_TEXT}; background-color: {_BG};"
            f"  font-size: 18pt; font-weight: bold; }}"
        )
        self._bpm_spin.valueChanged.connect(clock_gen.set_bpm)
        self._bpm_spin.setFixedHeight(self._bpm_spin.sizeHint().height())

        _bpm_btn_ss = (
            f"QPushButton {{ background-color: {_MUTE_OFF}; color: {_TEXT};"
            f"  border: none; border-radius: 3px; font-size: 11pt; padding: 0px; }}"
            f"QPushButton:hover {{ background-color: {_HOVER}; }}"
            f"QPushButton:disabled {{ color: {_HOVER}; background-color: {_PANEL}; }}"
        )
        self._bpm_up_btn = QPushButton("▲")
        self._bpm_up_btn.setFixedSize(22, 22)
        self._bpm_up_btn.setStyleSheet(_bpm_btn_ss)
        self._bpm_up_btn.clicked.connect(lambda: self._bpm_spin.stepBy(1))

        self._bpm_down_btn = QPushButton("▼")
        self._bpm_down_btn.setFixedSize(22, 22)
        self._bpm_down_btn.setStyleSheet(_bpm_btn_ss)
        self._bpm_down_btn.clicked.connect(lambda: self._bpm_spin.stepBy(-1))

        bpm_btn_col = QVBoxLayout()
        bpm_btn_col.setSpacing(2)
        bpm_btn_col.setContentsMargins(0, 0, 0, 0)
        bpm_btn_col.addStretch()
        bpm_btn_col.addWidget(self._bpm_up_btn)
        bpm_btn_col.addWidget(self._bpm_down_btn)
        bpm_btn_col.addStretch()

        bpm_spin_row = QHBoxLayout()
        bpm_spin_row.setSpacing(4)
        bpm_spin_row.setContentsMargins(0, 0, 0, 0)
        bpm_spin_row.addStretch(5)
        bpm_spin_row.addWidget(self._bpm_spin, alignment=Qt.AlignmentFlag.AlignVCenter)
        bpm_spin_row.addLayout(bpm_btn_col)
        bpm_spin_row.addSpacing(2)
        bpm_layout.addLayout(bpm_spin_row)

        bpm_layout.addStretch()
        tracks_row.addWidget(bpm_widget)
        tracks_row.addStretch()
        root.addLayout(tracks_row)

        # ── LFO panel ──
        self._lfo_panel = LfoPanel(engine, self._clock, self._get_strip_value)
        root.addWidget(self._lfo_panel)

        # ── Status bar ──
        status_row = QHBoxLayout()
        status_row.setContentsMargins(2, 4, 2, 0)

        status = QLabel(f"● Connected: {port_name}")
        status.setStyleSheet(f"color: {_GREEN}; font-size: 11pt; font-weight: bold;")
        status_row.addWidget(status)

        status_row.addStretch()

        mode_lbl = QLabel("Tempo Mode:")
        mode_lbl.setStyleSheet(f"color: {_DIM}; font-size: 11pt; font-weight: bold;")

        self._mode_btn = QPushButton(_MODE_LABEL[TempoMode.APP_CLOCK])
        self._mode_btn.setStyleSheet(
            f"QPushButton {{ color: {_DIM}; background-color: transparent;"
            f"  border: 1px solid {_GROOVE}; border-radius: 4px;"
            f"  font-size: 11pt; font-weight: bold; padding: 2px 8px; }}"
            f"QPushButton:hover {{ border-color: {_GRAY}; }}"
        )
        self._mode_btn.clicked.connect(self._toggle_mode)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(4)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._mode_btn)
        status_row.addLayout(mode_row)

        root.addLayout(status_row)

        # ── Mode detection timer ──
        self._tempo_mode = TempoMode.APP_CLOCK
        self._startup_detection_done = False
        self._mode_timer = QTimer(self)
        self._mode_timer.timeout.connect(self._poll_mode)
        self._mode_timer.start(500)

    # ------------------------------------------------------------------
    # Mode detection / toggle
    # ------------------------------------------------------------------

    def _set_mode(self, mode: TempoMode) -> None:
        self._tempo_mode = mode
        label = _MODE_LABEL[mode]

        self._mode_btn.setText(label)
        self._mode_btn.setStyleSheet(
            f"QPushButton {{ color: {_GREEN}; background-color: transparent;"
            f"  border: 1px solid {_GREEN}; border-radius: 4px;"
            f"  font-size: 11pt; font-weight: bold; padding: 2px 8px; }}"
            f"QPushButton:hover {{ background-color: #0f2a0f; }}"
        )
        if mode == TempoMode.OP1_CLOCK:
            # OP-1 is clock master — disable our clock output, BPM is read-only
            self._clock_gen.disable_clock()
            self._bpm_spin.setReadOnly(True)
            self._bpm_spin.setStyleSheet(
                f"QDoubleSpinBox {{ color: {_TEXT}; background-color: {_BG};"
                f"  font-size: 18pt; font-weight: bold; border: none; }}"
            )
            self._bpm_up_btn.setEnabled(False)
            self._bpm_down_btn.setEnabled(False)
        else:
            # App is clock master — enable our clock output, BPM is editable
            self._clock_gen.enable_clock()
            self._bpm_spin.setReadOnly(False)
            self._bpm_spin.setStyleSheet(
                f"QDoubleSpinBox {{ color: {_TEXT}; background-color: {_BG};"
                f"  font-size: 18pt; font-weight: bold;"
                f"  border: 1px solid {_DIM}; border-radius: 3px; }}"
            )
            self._bpm_up_btn.setEnabled(True)
            self._bpm_down_btn.setEnabled(True)

    def _toggle_mode(self) -> None:
        self._startup_detection_done = True  # manual override locks in the choice
        current = self._tempo_mode
        idx = (_MANUAL_CYCLE.index(current) + 1) % len(_MANUAL_CYCLE) if current in _MANUAL_CYCLE else 0
        self._set_mode(_MANUAL_CYCLE[idx])

    def _poll_mode(self) -> None:
        last = self._clock.last_tick_time
        receiving_ticks = last is not None and (time.perf_counter() - last) < 1.0

        if receiving_ticks and self._tempo_mode != TempoMode.OP1_CLOCK and not self._startup_detection_done:
            # OP-1 is sending clock → auto-detect as Beat Match
            self._startup_detection_done = True
            self._set_mode(TempoMode.OP1_CLOCK)
            QTimer.singleShot(5500, self._print_startup_log)
        elif not self._startup_detection_done:
            # First poll with no incoming ticks → OP-1 is in APP_CLOCK group
            self._startup_detection_done = True
            self._set_mode(TempoMode.APP_CLOCK)
            QTimer.singleShot(5500, self._print_startup_log)

        if self._tempo_mode == TempoMode.OP1_CLOCK:
            bpm = self._clock.bpm
            if bpm is not None:
                self._bpm_spin.blockSignals(True)
                self._bpm_spin.setValue(round(bpm, 1))
                self._bpm_spin.blockSignals(False)

    def _print_startup_log(self) -> None:
        """Log captured startup MIDI messages grouped by type (DEBUG level only)."""
        import math as _math
        from collections import Counter
        msgs = self._clock.startup_messages
        if not msgs:
            logging.debug("[startup] No MIDI messages received during startup window.")
            return
        counts: Counter[str] = Counter()
        clock_times: list[float] = []
        non_clock: list[tuple[float, str]] = []
        for elapsed, rep in msgs:
            # repr format: Message('clock', time=0)
            try:
                msg_type = rep.split("'")[1]
            except IndexError:
                msg_type = "unknown"
            counts[msg_type] += 1
            if msg_type == "clock":
                clock_times.append(elapsed)
            else:
                non_clock.append((elapsed, rep))
        logging.debug("[startup] %d total messages — counts by type: %s", len(msgs), dict(counts))
        if len(clock_times) >= 4:
            intervals = [clock_times[i+1] - clock_times[i] for i in range(len(clock_times) - 1)]
            mean = sum(intervals) / len(intervals)
            stddev = _math.sqrt(sum((x - mean) ** 2 for x in intervals) / len(intervals))
            bpm = 60.0 / (mean * 24)
            logging.debug("[startup] Clock jitter: mean=%.3fms  stddev=%.3fms  BPM≈%.1f",
                          mean * 1000, stddev * 1000, bpm)
        if non_clock:
            logging.debug("[startup] Non-clock messages:")
            for elapsed, rep in non_clock:
                logging.debug("  +%.3fs  %s", elapsed, rep)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_beat(self, beat_num: int) -> None:
        self._lfo_panel.on_beat(beat_num)

    def _on_automation_update(self, track: int, param_name: str, value: int) -> None:
        strip = self._strips.get(track)
        if strip:
            strip.set_automation_value(param_name, value)

    def _on_cc_received(self, channel: int, control: int, value: int) -> None:
        strip = self._strips.get(channel + 1)
        if strip:
            strip.update_from_cc(control, value)

    def _get_strip_value(self, track: int, param: Parameter) -> int:
        strip = self._strips.get(track)
        return strip.current_midi_value(param) if strip else 64

