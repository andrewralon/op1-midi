"""PyQt6 mixer UI for the OP-1 Field controller."""

import logging
import math

log = logging.getLogger(__name__)
import os
import time
from enum import Enum, auto

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QSlider, QDial, QFrame, QSizePolicy,
    QApplication, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox,
    QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QPointF, QRectF, QSize, QTimer
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QPolygonF
from PyQt6.QtSvg import QSvgRenderer

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
_WHITE      = "#ffffff"
_BLACK      = "#000000"
_BLUESTEEL  = "#132542"
_GOLD       = "#fddf28"
_BLUEGRAY   = "#5c5c74"
_ORANGERED  = "#ff5349"
_GRAY       = "#555555"
_GREEN      = "#4ec94e"
_DARKGREEN  = "#1e4a1e"
_RED        = "#ff4444"
# OP-1 Field per-track colors, matched from the device's mixer screen
TRACK_COLORS = {
    1: _BLUE_1,    # steel blue
    2: _OCHRE_2,   # ochre
    3: _GRAY_3,    # blue gray
    4: _ORANGE_4,  # orange
}

# OTHER - UI ASSETS
_ASSETS = os.path.dirname(os.path.abspath(__file__)) + "/assets/"
_ARROW_UP_SVG   = _ASSETS + "arrow_up.svg"
_ARROW_DOWN_SVG = _ASSETS + "arrow_down.svg"
_METRONOME_SVG  = _ASSETS + "metronome.svg"
_DEPTH_SVG      = _ASSETS + "depth.svg"
_CENTER_SVG     = _ASSETS + "center.svg"
_WAVE_SVG       = _ASSETS + "wave.svg"

# OTHER - UI CONSTRAINTS
_LABEL_GAP  = 12  # px between a label and its paired control (dropdown, spinbox, etc.)
_ICON_PT    = 22  # pt size for unicode icon labels


# ---------------------------------------------------------------------------
# Tempo mode
# ---------------------------------------------------------------------------

class TempoMode(Enum):
    APP_CLOCK = auto()  # auto-detected: OP-1 silent (MIDI SYNC or FREE)
    OP1_CLOCK = auto()  # auto-detected: OP-1 sending clock (BEAT MATCH, PO SYNC, or 1/16)

_MODE_LABEL: dict[TempoMode, str] = {
    TempoMode.APP_CLOCK: "app (MIDI SYNC)",
    TempoMode.OP1_CLOCK: "op1 (BEAT MATCH)",
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



class SvgIcon(QWidget):
    """Renders an SVG file at a fixed logical size. Qt handles Retina scaling automatically."""
    def __init__(self, path: str, height: int, parent=None):
        super().__init__(parent)
        self._renderer = QSvgRenderer(path)
        sz = self._renderer.defaultSize()
        width = max(1, int(height * sz.width() / max(1, sz.height())))
        self.setFixedSize(width, height)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._renderer.render(p, QRectF(self.rect()))
        p.end()


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
    automation_update = pyqtSignal(int, str, float)
    cc_received       = pyqtSignal(int, int, int)
    disconnected      = pyqtSignal()
    reconnected       = pyqtSignal()


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

        # Min/max indicator triangles just outside the knob rim, pointing toward center
        tri_dist = r + 9.0   # base distance from center
        tri_h = 5.0           # height (base to tip, along radial toward center)
        tri_hb = 2.0          # half-width of base (perpendicular to radial)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(_DIM))
        for angle_deg in (-135.0, 135.0):
            da = math.radians(angle_deg)
            ds, dc = math.sin(da), math.cos(da)
            tip = QPointF(cx + ds * (tri_dist - tri_h), cy - dc * (tri_dist - tri_h))
            bx = cx + ds * tri_dist
            by = cy - dc * tri_dist
            bl = QPointF(bx + dc * tri_hb,  by + ds * tri_hb)
            br = QPointF(bx - dc * tri_hb,  by - ds * tri_hb)
            p.drawPolygon(QPolygonF([tip, bl, br]))

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
# 7-segment digit widget
# ---------------------------------------------------------------------------

class SegmentDigit(QWidget):
    """Draws a single digit (0–9) as a classic 7-segment LED display."""

    # segments: a=top, b=top-right, c=bot-right, d=bottom, e=bot-left, f=top-left, g=middle
    _MAP = {
        '0': (1,1,1,1,1,1,0),
        '1': (0,1,1,0,0,0,0),
        '2': (1,1,0,1,1,0,1),
        '3': (1,1,1,1,0,0,1),
        '4': (0,1,1,0,0,1,1),
        '5': (1,0,1,1,0,1,1),
        '6': (1,0,1,1,1,1,1),
        '7': (1,1,1,0,0,0,0),
        '8': (1,1,1,1,1,1,1),
        '9': (1,1,1,1,0,1,1),
    }

    def __init__(self, char='0', parent=None):
        super().__init__(parent)
        self._char = char
        self.setFixedSize(22, 46)

    def set_char(self, c: str) -> None:
        if c != self._char:
            self._char = c
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        w, h = float(self.width()), float(self.height())
        t   = 3.5   # segment thickness
        pad = 1.5   # outer padding
        gap = 1.0   # gap between segment ends

        xl = pad                  # left edge of vertical segs
        xr = w - pad - t          # right edge of vertical segs
        yt = pad                  # top of top horiz seg
        ym = h / 2.0 - t / 2.0   # top of middle horiz seg
        yb = h - pad - t          # top of bottom horiz seg

        hx0 = xl + t + gap
        hx1 = xr - gap
        hw  = hx1 - hx0

        vt0, vt1 = yt + t + gap, ym - gap
        vb0, vb1 = ym + t + gap, yb - gap

        segs = self._MAP.get(self._char, (0,)*7)
        on  = QColor(_TEXT)
        off = QColor("#282828")

        def hseg(y, lit):
            p.setBrush(on if lit else off)
            p.drawRect(QPointF(hx0, y).toPoint().x(), int(y), int(hw), int(t))

        def vseg(x, y0, y1, lit):
            p.setBrush(on if lit else off)
            p.drawRect(int(x), int(y0), int(t), int(y1 - y0))

        hseg(yt,  segs[0])
        vseg(xr,  vt0, vt1, segs[1])
        vseg(xr,  vb0, vb1, segs[2])
        hseg(yb,  segs[3])
        vseg(xl,  vb0, vb1, segs[4])
        vseg(xl,  vt0, vt1, segs[5])
        hseg(ym,  segs[6])

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
        self._rate_ticks      = PPQN   # default: 1 cycle per beat
        self._normal_colors: list[str]   = [_ACCENT]
        self._inverted_colors: list[str] = []
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

    def set_colors(self, normal_colors: list[str], inverted_colors: list[str]) -> None:
        self._normal_colors   = normal_colors
        self._inverted_colors = inverted_colors
        self.update()

    _SEGMENT_PX = 20  # pixels per color alternation segment when multiple tracks are selected

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
        n_cycles = 8.0 * PPQN / self._rate_ticks
        steps    = w * 2

        if self._normal_colors:
            self._draw_curve(p, steps, w, cy, amplitude, n_cycles, self._normal_colors, inverted=False)
        if self._inverted_colors:
            self._draw_curve(p, steps, w, cy, amplitude, n_cycles, self._inverted_colors, inverted=True)

        p.end()

    def _draw_curve(
        self, p: QPainter, steps: int, w: int, cy: float, amplitude: float,
        n_cycles: float, colors: list[str], *, inverted: bool,
    ) -> None:
        single     = len(colors) == 1
        prev_pt    = None
        prev_color = None
        for i in range(steps + 1):
            phase  = (i / steps) * n_cycles
            y_norm = lfo_wave_value(phase % 1.0, self._wave)
            if inverted:
                y_norm = -y_norm
            px = float(i) * w / steps
            py = cy - y_norm * amplitude
            pt = QPointF(px, py)
            if prev_pt is not None:
                if single:
                    color = colors[0]
                else:
                    mid_x     = (prev_pt.x() + pt.x()) / 2.0
                    color_idx = int(mid_x / self._SEGMENT_PX) % len(colors)
                    color     = colors[color_idx]
                if color != prev_color:
                    pen = QPen(QColor(color), 2)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    p.setPen(pen)
                    prev_color = color
                p.drawLine(prev_pt, pt)
            prev_pt = pt


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

        self._pan_dial = PanDial()
        self._pan_dial.setRange(0, 128)
        self._pan_dial.setValue(64)
        self._pan_dial.setNotchesVisible(False)
        self._pan_dial.setWrapping(False)
        self._pan_dial.setFixedSize(44, 44)
        self._pan_dial.valueChanged.connect(self._on_pan_changed)

        pan_row = QHBoxLayout()
        pan_row.setContentsMargins(0, 0, 0, 0)
        pan_row.addWidget(self._pan_dial, alignment=Qt.AlignmentFlag.AlignCenter)
        body.addLayout(pan_row)

        # Volume fader: [digit1] [slider] [digit2] centered in column
        fader_row = QHBoxLayout()
        fader_row.setSpacing(0)
        fader_row.setContentsMargins(0, 0, 0, 0)

        _init = f"{_midi_to_ui(115):02d}"
        self._vol_d1 = SegmentDigit(_init[0])
        self._vol_d2 = SegmentDigit(_init[1])

        self._vol_slider = QSlider(Qt.Orientation.Vertical)
        self._vol_slider.setRange(0, 127)
        self._vol_slider.setValue(115)
        self._vol_slider.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._vol_slider.setMinimumHeight(110)
        self._vol_slider.setFixedWidth(20)
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
            "  width: 20px; height: 10px;"
            "  margin: 0 -8px; border-radius: 3px;"
            "}"
        )
        self._vol_slider.valueChanged.connect(self._on_volume_changed)

        fader_row.addStretch()
        fader_row.addWidget(self._vol_d1, alignment=Qt.AlignmentFlag.AlignVCenter)
        fader_row.addWidget(self._vol_slider, alignment=Qt.AlignmentFlag.AlignVCenter)
        fader_row.addWidget(self._vol_d2, alignment=Qt.AlignmentFlag.AlignVCenter)
        fader_row.addStretch()

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
        _s = f"{_midi_to_ui(value):02d}"; self._vol_d1.set_char(_s[0]); self._vol_d2.set_char(_s[1])
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
            _s = f"{_midi_to_ui(value):02d}"; self._vol_d1.set_char(_s[0]); self._vol_d2.set_char(_s[1])
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
            _s = f"{_midi_to_ui(value):02d}"; self._vol_d1.set_char(_s[0]); self._vol_d2.set_char(_s[1])
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
# LFO track selector button (3-state: off / normal / inverted)
# ---------------------------------------------------------------------------

class TrackBtn(QPushButton):
    state_changed = pyqtSignal(int)

    def __init__(self, label: str, track: int, initial_state: int = 0, parent=None):
        super().__init__(label, parent)
        self._track = track
        self._state = initial_state
        self.setFlat(True)
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        self.setFont(f)
        self.clicked.connect(self._cycle)

    @property
    def state(self) -> int:
        return self._state

    def set_state(self, state: int) -> None:
        if state != self._state:
            self._state = state
            self.update()
            self.state_changed.emit(state)

    def _cycle(self) -> None:
        self.set_state((self._state + 1) % 3)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.3)
        rect = self.rect().adjusted(0, 0, -1, -1)
        color = QColor(TRACK_COLORS[self._track])
        if self._state == 0:
            bg, fg = QColor(_BLACK), color
        else:
            bg, fg = color, QColor(_BLACK)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(rect, 4, 4)
        p.setPen(fg)
        p.setFont(self.font())
        if self._state == 2:
            cx = (rect.width() + 1) / 2.0
            cy = (rect.height() + 1) / 2.0
            p.translate(cx, cy)
            p.rotate(180)
            p.translate(-cx, -cy)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


# ---------------------------------------------------------------------------
# LFO modulator panel
# ---------------------------------------------------------------------------

class LfoPanel(QFrame):
    def __init__(self, engine: AutomationEngine, clock, get_value_fn, get_bpm_fn=None, set_bpm_fn=None, parent=None):
        super().__init__(parent)
        self._engine       = engine
        self._clock        = clock
        self._get_value    = get_value_fn
        self._get_bpm      = get_bpm_fn
        self._set_bpm      = set_bpm_fn
        self._active_lfos: list[LfoClip] = []
        self._bpm_original: float | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            f"LfoPanel {{ background-color: {_PANEL}; border-radius: 8px;"
            f"  border: 1px solid {_BORDER}; }}"
        )

        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.setContentsMargins(14, 10, 14, 10)

        # ── Row 1: title + Track buttons / Param / Wave ──
        hdr = QHBoxLayout()
        hdr.setSpacing(0)

        hdr.addStretch(1)

        # Track toggle buttons — create before wiring signals to avoid premature callbacks
        self._track_btns: dict[int, TrackBtn] = {}
        for t in (1, 2, 3, 4):
            btn = TrackBtn(str(t), t, initial_state=1 if t == 1 else 0)
            btn.setFixedSize(28, 28)
            self._track_btns[t] = btn
            hdr.addWidget(btn)
            if t < 4:
                hdr.addSpacing(_LABEL_GAP)

        hdr.addStretch(1)
        self._param_combo = self._make_combo(list(PARAMETER_LABELS))
        self._wave_combo  = self._make_combo(list(LFO_WAVE_LABELS))

        hdr.addWidget(self._dim_label("☂", _ICON_PT))
        hdr.addSpacing(_LABEL_GAP)
        hdr.addWidget(self._param_combo)

        hdr.addStretch(1)
        hdr.addWidget(SvgIcon(_WAVE_SVG, 22))
        hdr.addSpacing(_LABEL_GAP)
        hdr.addWidget(self._wave_combo)
        hdr.addStretch(1)

        root.addLayout(hdr)

        # ── Row 2: waveform preview ──
        self._preview = WaveformPreview()
        root.addWidget(self._preview)

        self._range_label = QLabel()
        self._range_label.setStyleSheet(f"color: {_DIM}; font-size: 12pt;")
        self._range_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # ── Row 3: Rate / Depth / Center ──
        params_row = QHBoxLayout()
        params_row.setSpacing(0)

        _spin_style = (
            f"QSpinBox {{ color: {_TEXT}; background-color: {_BG};"
            f"  border: 1px solid {_DIM}; border-radius: 4px;"
            f"  font-size: 13pt; padding: 2px 4px; }}"
            f"QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;"
            f"  width: 16px; background-color: {_BG}; border-left: 1px solid {_DIM};"
            f"  border-bottom: 1px solid {_DIM}; }}"
            f"QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;"
            f"  width: 16px; background-color: {_BG}; border-left: 1px solid {_DIM}; }}"
            f"QSpinBox::up-arrow {{ image: url({_ARROW_UP_SVG}); width: 8px; height: 5px; }}"
            f"QSpinBox::down-arrow {{ image: url({_ARROW_DOWN_SVG}); width: 8px; height: 5px; }}"
        )
        _double_spin_style = _spin_style.replace("QSpinBox", "QDoubleSpinBox")

        self._rate_spin = QSpinBox()
        self._rate_spin.setRange(1, 8)
        self._rate_spin.setValue(3)   # default: 4 beats/cycle
        self._rate_spin.setFixedWidth(56)
        self._rate_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rate_spin.setStyleSheet(_spin_style)

        self._rate_spin.valueChanged.connect(lambda _: self._update_preview())

        self._depth_spin = QSpinBox()
        self._depth_spin.setRange(0, 49)
        self._depth_spin.setValue(25)
        self._depth_spin.setFixedWidth(66)
        self._depth_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._depth_spin.setStyleSheet(_spin_style)

        self._center_spin = QDoubleSpinBox()
        self._center_spin.setDecimals(1)
        self._center_spin.setSingleStep(0.1)
        self._center_spin.setRange(0.0, 99.0)
        self._center_spin.setValue(50.0)  # ≈ MIDI 64 (center)
        self._center_spin.setFixedWidth(78)
        self._center_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._center_spin.setStyleSheet(_double_spin_style)

        use_cur_btn = QPushButton("Current")
        use_cur_btn.setStyleSheet(
            f"QPushButton {{ background-color: {_HOVER}; color: {_TEXT};"
            f"  border: none; border-radius: 4px; font-size: 12pt;"
            f"  padding: 4px 14px; }}"
            f"QPushButton:hover {{ background-color: {_KNOB_RIM}; }}"
        )
        use_cur_btn.clicked.connect(self._on_use_current)

        params_row.addWidget(self._dim_label("⏱", _ICON_PT))
        params_row.addSpacing(_LABEL_GAP)
        params_row.addWidget(self._rate_spin)
        params_row.addStretch(1)
        params_row.addWidget(SvgIcon(_DEPTH_SVG, 30))
        params_row.addSpacing(_LABEL_GAP)
        params_row.addWidget(self._depth_spin)
        params_row.addStretch(1)
        params_row.addWidget(SvgIcon(_CENTER_SVG, 30))
        params_row.addSpacing(_LABEL_GAP)
        params_row.addWidget(self._center_spin)
        params_row.addStretch(1)
        params_row.addWidget(use_cur_btn)
        params_row.addStretch(1)
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

        self._lfo_list = QListWidget()
        self._lfo_list.setStyleSheet(
            f"QListWidget {{ background-color: {_BG}; color: {_TEXT};"
            f"  border: 1px solid {_BORDER}; border-radius: 4px; font-size: 10pt; }}"
        )
        self._lfo_list.setFixedHeight(96)  # 3×28px buttons + 2×6px gaps

        bottom_row.addLayout(btn_col)
        bottom_row.addWidget(self._dim_label("Active LFOs"), alignment=Qt.AlignmentFlag.AlignTop)
        bottom_row.addWidget(self._lfo_list, stretch=1)
        root.addLayout(bottom_row)

        # Wire up live preview and param changes
        self._param_combo.currentTextChanged.connect(self._on_param_changed)
        self._wave_combo.currentTextChanged.connect(self._update_preview)
        self._depth_spin.valueChanged.connect(self._update_preview)
        self._center_spin.valueChanged.connect(self._update_preview)
        for btn in self._track_btns.values():
            btn.state_changed.connect(self._update_preview)
        self._update_preview()

    # ------------------------------------------------------------------

    def _make_combo(self, items: list[str]) -> QComboBox:
        box = QComboBox()
        box.addItems(items)
        box.setStyleSheet(
            f"QComboBox {{ font-size: 13pt; color: {_TEXT}; background-color: {_BG};"
            f"  border: 1px solid {_DIM}; border-radius: 4px; padding: 2px 4px; }}"
            f"QComboBox QAbstractItemView {{ color: {_TEXT}; background-color: {_BG};"
            f"  selection-background-color: {_ACCENT}; selection-color: #000; }}"
        )
        return box

    def _dim_label(self, text: str, pt: int = 12) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {_DIM}; font-size: {pt}pt; font-weight: bold;")
        return lbl

    def _on_param_changed(self, text: str) -> None:
        param = PARAMETER_LABELS.get(text)
        is_tempo = param is Parameter.TEMPO

        for btn in self._track_btns.values():
            btn.setEnabled(not is_tempo)

        self._depth_spin.blockSignals(True)
        self._center_spin.blockSignals(True)
        if is_tempo:
            self._depth_spin.setRange(0, 140)
            self._center_spin.setRange(20.0, 300.0)
            current_bpm = self._get_bpm() if self._get_bpm else 100.0
            self._center_spin.setValue(current_bpm)
            self._depth_spin.setValue(10)
        else:
            self._depth_spin.setRange(0, 49)
            self._center_spin.setRange(0.0, 99.0)
            self._center_spin.setValue(50.0)
            self._depth_spin.setValue(25)
        self._depth_spin.blockSignals(False)
        self._center_spin.blockSignals(False)
        self._update_preview()

    def _update_preview(self, *_) -> None:
        wave       = LFO_WAVE_LABELS[self._wave_combo.currentText()]
        rate_ticks = _RATE_TICKS[self._rate_spin.value()]
        param      = PARAMETER_LABELS[self._param_combo.currentText()]

        if param is Parameter.TEMPO:
            normal_colors   = [_ACCENT]
            inverted_colors = []
        else:
            normal_tracks   = [t for t, btn in self._track_btns.items() if btn.state == 1]
            inverted_tracks = [t for t, btn in self._track_btns.items() if btn.state == 2]
            if not normal_tracks and not inverted_tracks:
                normal_colors   = [_ACCENT]
                inverted_colors = []
            else:
                normal_colors   = [TRACK_COLORS[t] for t in normal_tracks]
                inverted_colors = [TRACK_COLORS[t] for t in inverted_tracks]
        self._preview.set_colors(normal_colors, inverted_colors)

        if param is Parameter.TEMPO:
            center = self._center_spin.value()
            depth  = self._depth_spin.value()
            self._preview.set_params(wave, depth, center, rate_ticks)
            lo = max(0.0,  center - depth)
            hi = min(300.0, center + depth)
            self._range_label.setText(f"{lo:.1f}–{hi:.1f}")
        else:
            depth_midi  = _ui_to_midi(self._depth_spin.value())
            center_midi = _ui_to_midi(self._center_spin.value())
            self._preview.set_params(wave, depth_midi, center_midi, rate_ticks)
            lo = _midi_to_ui(max(0,   center_midi - depth_midi))
            hi = _midi_to_ui(min(127, center_midi + depth_midi))
            self._range_label.setText(f"{lo:.1f}–{hi:.1f}")

    def _on_use_current(self) -> None:
        param = PARAMETER_LABELS[self._param_combo.currentText()]
        if param is Parameter.TEMPO:
            if self._get_bpm:
                self._center_spin.setValue(self._get_bpm())
            return
        selected = [t for t, btn in self._track_btns.items() if btn.state != 0]
        if not selected:
            return
        midi_val = self._get_value(selected[0], param)
        self._center_spin.setValue(_midi_to_ui(midi_val))

    def _on_start(self) -> None:
        param      = PARAMETER_LABELS[self._param_combo.currentText()]
        wave       = LFO_WAVE_LABELS[self._wave_combo.currentText()]
        rate_ticks = _RATE_TICKS[self._rate_spin.value()]

        if param is Parameter.TEMPO:
            if self._bpm_original is None and self._get_bpm:
                self._bpm_original = self._get_bpm()
            # Replace any existing Tempo LFO (only one makes sense globally)
            for lfo in [l for l in self._active_lfos if l.parameter is Parameter.TEMPO]:
                self._engine.remove_lfo(lfo)
                self._active_lfos.remove(lfo)
            lfo = LfoClip(
                track        = 0,
                parameter    = Parameter.TEMPO,
                wave         = wave,
                rate_ticks   = rate_ticks,
                depth        = self._depth_spin.value(),
                center_value = self._center_spin.value(),
                inverted     = False,
            )
            self._engine.add_lfo(lfo)
            self._active_lfos.append(lfo)
            self._refresh_list()
            return

        active = [(t, btn) for t, btn in self._track_btns.items() if btn.state != 0]
        if not active:
            return
        depth        = _ui_to_midi(self._depth_spin.value())
        center_value = _ui_to_midi(self._center_spin.value())
        for t, btn in active:
            lfo = LfoClip(
                track        = t,
                parameter    = param,
                wave         = wave,
                rate_ticks   = rate_ticks,
                depth        = depth,
                center_value = center_value,
                inverted     = btn.state == 2,
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
            self._maybe_restore_bpm()

    def _on_stop_all(self) -> None:
        self._engine.clear_lfos()
        self._active_lfos.clear()
        self._refresh_list()
        self._maybe_restore_bpm()

    def _maybe_restore_bpm(self) -> None:
        if self._bpm_original is not None:
            if not any(l.parameter is Parameter.TEMPO for l in self._active_lfos):
                if self._set_bpm:
                    self._set_bpm(self._bpm_original)
                self._bpm_original = None

    def _refresh_list(self) -> None:
        self._lfo_list.clear()
        for lfo in self._active_lfos:
            if lfo.rate_ticks >= PPQN:
                rate_str = f"{lfo.rate_ticks // PPQN}b/cycle"
            else:
                rate_str = f"{PPQN // lfo.rate_ticks}×/beat"
            if lfo.parameter is Parameter.TEMPO:
                lo = max(20,  lfo.center_value - lfo.depth)
                hi = min(300, lfo.center_value + lfo.depth)
                self._lfo_list.addItem(QListWidgetItem(
                    f"Tempo  {lfo.wave.value}  {lo:.1f}↔{hi:.1f}bpm  {rate_str}"
                ))
            else:
                lo = _midi_to_ui(max(0,   lfo.center_value - lfo.depth))
                hi = _midi_to_ui(min(127, lfo.center_value + lfo.depth))
                inv_str = " [inv]" if lfo.inverted else ""
                self._lfo_list.addItem(QListWidgetItem(
                    f"T{lfo.track}  {lfo.parameter.value.upper()[:3]}  "
                    f"{lfo.wave.value}  {lo:.1f}↔{hi:.1f}  {rate_str}{inv_str}"
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
        self._controller        = controller
        self._clock             = clock
        self._clock_gen         = clock_gen
        self._transport_playing = False
        self._transport_stopped = False
        self._strips: dict[int, TrackStrip] = {}
        self._setup_ui(controller, engine, port_name, clock_gen)

        bridge.beat.connect(self._on_beat)
        bridge.automation_update.connect(self._on_automation_update)
        bridge.cc_received.connect(self._on_cc_received)
        bridge.disconnected.connect(self._on_disconnected)
        bridge.reconnected.connect(self._on_reconnected)

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
            f"  border: none; border-radius: 6px; font-size: 18pt; }}"
            f"QPushButton:hover {{ background-color: {_HOVER}; }}"
            f"QPushButton:pressed {{ background-color: #4a4a4a; }}"
        )

        def _make_btn(label: str) -> QPushButton:
            b = QPushButton(label)
            b.setFixedSize(44, 44)
            b.setStyleSheet(_btn_ss)
            return b

        play_btn     = _make_btn("▶")
        stop_btn     = _make_btn("■")
        oct_left_btn = _make_btn("←")
        oct_right_btn = _make_btn("→")

        play_btn.clicked.connect(self._on_transport_play)
        stop_btn.clicked.connect(self._on_transport_stop)
        oct_left_btn.clicked.connect(clock_gen.tape_prev_bar)
        oct_right_btn.clicked.connect(clock_gen.tape_next_bar)

        transport_row = QHBoxLayout()
        transport_row.setSpacing(8)
        transport_row.addWidget(play_btn)
        transport_row.addWidget(stop_btn)

        octave_row = QHBoxLayout()
        octave_row.setSpacing(8)
        octave_row.addWidget(oct_left_btn)
        octave_row.addWidget(oct_right_btn)

        btn_widget = QWidget()
        btn_widget.setFixedWidth(105)
        btn_col = QVBoxLayout(btn_widget)
        btn_col.setSpacing(10)
        btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.addStretch()
        btn_col.addLayout(transport_row)
        btn_col.addLayout(octave_row)
        btn_col.addStretch()

        # ── Track strips, centered as a group with button column ──
        tracks_row = QHBoxLayout()
        tracks_row.setSpacing(10)
        tracks_row.addStretch()
        tracks_row.addWidget(btn_widget)
        for t in (1, 2, 3, 4):
            strip = TrackStrip(t, controller)
            self._strips[t] = strip
            tracks_row.addWidget(strip)

        bpm_widget = QWidget()
        bpm_widget.setFixedWidth(105)
        bpm_layout = QVBoxLayout(bpm_widget)
        bpm_layout.setSpacing(1)
        bpm_layout.setContentsMargins(2, 0, 2, 0)
        bpm_layout.addStretch()

        bpm_title = SvgIcon(_METRONOME_SVG, 36)
        bpm_layout.addWidget(bpm_title, alignment=Qt.AlignmentFlag.AlignCenter)

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
        self._lfo_panel = LfoPanel(
            engine, self._clock, self._get_strip_value,
            get_bpm_fn=lambda: self._bpm_spin.value(),
            set_bpm_fn=self._set_bpm_from_lfo,
        )
        root.addWidget(self._lfo_panel)

        # ── Status bar ──
        status_row = QHBoxLayout()
        status_row.setContentsMargins(2, 4, 2, 0)

        self._conn_label = QLabel(f"● Connected: {port_name}")
        self._conn_label.setStyleSheet(f"color: {_GREEN}; font-size: 11pt; font-weight: bold;")
        self._conn_port_name = port_name
        status_row.addWidget(self._conn_label)

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

    def _on_transport_play(self) -> None:
        self._transport_playing = True
        self._transport_stopped = False
        self._clock_gen.play()

    def _on_transport_stop(self) -> None:
        if self._transport_playing:
            self._transport_playing = False
            self._transport_stopped = True
            self._clock_gen.stop()
        elif self._transport_stopped:
            self._transport_stopped = False
            self._clock_gen.goto_start()

    def _on_disconnected(self) -> None:
        self._conn_label.setText(f"● Disconnected: {self._conn_port_name} — Reconnecting...")
        self._conn_label.setStyleSheet(f"color: {_RED}; font-size: 11pt; font-weight: bold;")

    def _on_reconnected(self) -> None:
        self._conn_label.setText(f"● Connected: {self._conn_port_name}")
        self._conn_label.setStyleSheet(f"color: {_GREEN}; font-size: 11pt; font-weight: bold;")

    def _on_beat(self, beat_num: int) -> None:
        self._lfo_panel.on_beat(beat_num)

    def _on_automation_update(self, track: int, param_name: str, value: float) -> None:
        log.debug("_on_automation_update: param=%s value=%s (type %s)", param_name, value, type(value).__name__)
        if param_name == Parameter.TEMPO.value:
            self._set_bpm_from_lfo(value)
            return
        strip = self._strips.get(track)
        if strip:
            strip.set_automation_value(param_name, int(value))

    def _set_bpm_from_lfo(self, bpm: float) -> None:
        self._clock_gen.set_bpm(bpm)
        self._bpm_spin.blockSignals(True)
        self._bpm_spin.setValue(bpm)
        self._bpm_spin.blockSignals(False)

    def _on_cc_received(self, channel: int, control: int, value: int) -> None:
        strip = self._strips.get(channel + 1)
        if strip:
            strip.update_from_cc(control, value)

    def _get_strip_value(self, track: int, param: Parameter) -> int:
        strip = self._strips.get(track)
        return strip.current_midi_value(param) if strip else 64

