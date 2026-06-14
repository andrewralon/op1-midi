"""
Remote WebSocket server for op1-lfo-hero.

Serves a mobile-friendly control surface at http://<mac-ip>:8765/.
Runs uvicorn in a background daemon thread so the PyQt6 event loop is unaffected.

Clients connect to ws://<host>:8765/ws and receive JSON state snapshots every
200 ms (plus immediately after each command). Commands are JSON objects with a
"cmd" key; state snapshots are JSON objects with "type": "state".

Known limitation (v1): LFOs added from the web UI appear in engine.lfos and
are controlled correctly, but the desktop's Active LFO list does not show them.
The desktop "Stop All" (⌫) button will still stop everything via engine.clear_lfos().
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from src.automation import (
    LfoClip,
    LfoWave,
    Parameter,
    LFO_WAVE_LABELS,
    PARAMETER_LABELS,
    AutomationEngine,
)
from src.clock import PPQN
from src.controller import Controller

log = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent / "web"

PORT = 8765

# Rate spinbox value (1-8) → ticks per LFO cycle (mirrors ui.py _RATE_TICKS)
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
_TICKS_TO_RATE: dict[int, int] = {v: k for k, v in _RATE_TICKS.items()}


def _midi_to_ui(v: int | float) -> int:
    """MIDI 0-127 → display 0-99 (OP-1 scale)."""
    return int(round(v)) * 99 // 127


def _ui_to_midi(v: float) -> int:
    """Display 0-99 → MIDI 0-127 (ceiling inverse for perfect round-trip)."""
    return (round(v) * 127 + 98) // 99


class RemoteServer:
    """FastAPI + uvicorn WebSocket server. Call start() once after construction."""

    def __init__(
        self,
        controller: Controller,
        clock_gen: Any,        # MidiClockGenerator — avoid circular import
        engine: AutomationEngine,
    ) -> None:
        self._ctrl = controller
        self._clock_gen = clock_gen
        self._engine = engine

        # Local volume/pan state in MIDI units — init to app defaults
        # (controller doesn't track sent values; we mirror them here)
        self._vol: dict[int, int] = {t: 116 for t in (1, 2, 3, 4)}  # MIDI 116 = display 90
        self._pan: dict[int, int] = {t: 64  for t in (1, 2, 3, 4)}  # MIDI 64 = center

        self._clients: set[WebSocket] = set()
        self._app = self._build_app()

    # ── FastAPI wiring ─────────────────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(docs_url=None, redoc_url=None)

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(str(_WEB_DIR / "index.html"))

        @app.get("/manifest.json")
        async def manifest():
            from fastapi.responses import Response
            data = json.dumps({
                "name": "LFO Hero Remote",
                "short_name": "LFO Hero",
                "start_url": "/",
                "display": "standalone",
                "background_color": "#111111",
                "theme_color": "#111111",
                "orientation": "portrait",
                "icons": [],
            })
            return Response(content=data, media_type="application/manifest+json")

        @app.websocket("/ws")
        async def ws_endpoint(ws: WebSocket) -> None:
            await ws.accept()
            self._clients.add(ws)
            try:
                await ws.send_text(json.dumps(self._snapshot()))
                async for raw in ws.iter_text():
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    await self._handle(msg)
                    # Echo back updated state immediately after each command
                    try:
                        await ws.send_text(json.dumps(self._snapshot()))
                    except Exception:
                        break
            except WebSocketDisconnect:
                pass
            except Exception:
                pass
            finally:
                self._clients.discard(ws)

        return app

    # ── State snapshot ─────────────────────────────────────────────────────────

    def _snapshot(self) -> dict[str, Any]:
        bpm = float(self._clock_gen.bpm)
        playing = bool(getattr(self._clock_gen, "is_playing", False))
        tracks = [
            {
                "volume": _midi_to_ui(self._vol[t]),
                "pan":    self._pan[t] - 64,       # -63..+63, 0 = center
                "muted":  self._ctrl.is_muted(t),
            }
            for t in (1, 2, 3, 4)
        ]
        lfos: list[dict[str, Any]] = []
        for lfo in self._engine.lfos:
            rate = _TICKS_TO_RATE.get(lfo.rate_ticks, 3)
            is_tempo = lfo.parameter is Parameter.TEMPO
            lfos.append({
                "id":        id(lfo),
                "wave":      lfo.wave.value,
                "track":     lfo.track,
                "parameter": lfo.parameter.value,
                "loop":      lfo.loop,
                "inverted":  lfo.inverted,
                "rate":      rate,
                "depth":     lfo.depth        if is_tempo else _midi_to_ui(lfo.depth),
                "center":    lfo.center_value if is_tempo else _midi_to_ui(lfo.center_value),
            })
        return {
            "type":       "state",
            "bpm":        round(bpm, 1),
            "is_playing": playing,
            "tracks":     tracks,
            "lfos":       lfos,
        }

    # ── Command dispatch ───────────────────────────────────────────────────────

    async def _handle(self, msg: dict[str, Any]) -> None:
        cmd = str(msg.get("cmd", ""))
        try:
            match cmd:
                case "set_volume":
                    t, v = int(msg["track"]), float(msg["value"])
                    midi = _ui_to_midi(max(0.0, min(99.0, v)))
                    self._vol[t] = midi
                    self._ctrl.set_volume(t, midi)
                case "set_pan":
                    t, v = int(msg["track"]), float(msg["value"])   # -63..+63
                    midi = max(0, min(127, round(v) + 64))
                    self._pan[t] = midi
                    self._ctrl.set_pan(t, midi)
                case "toggle_mute":
                    self._ctrl.toggle_mute(int(msg["track"]))
                case "set_bpm":
                    self._clock_gen.set_bpm(float(msg["value"]))
                case "play":
                    self._clock_gen.play()
                case "stop":
                    self._clock_gen.stop()
                case "tape_prev":
                    self._clock_gen.tape_prev_bar()
                case "tape_next":
                    self._clock_gen.tape_next_bar()
                case "lfo_start":
                    self._lfo_start(msg)
                case "lfo_stop":
                    self._lfo_stop(int(msg.get("id", 0)))
                case "lfo_stop_all":
                    self._engine.clear_lfos()
        except Exception as exc:
            log.warning("remote cmd %r failed: %s", cmd, exc)

    def _lfo_start(self, msg: dict[str, Any]) -> None:
        wave_str  = str(msg.get("wave", "sine"))
        wave      = LFO_WAVE_LABELS.get(wave_str, LfoWave.SINE)
        rate_ticks = _RATE_TICKS.get(int(msg.get("rate", 3)), 4 * PPQN)
        depth_ui  = float(msg.get("depth", 25.0))
        center_ui = float(msg.get("center", 90.0))
        param_str = str(msg.get("parameter", "volume"))
        param     = PARAMETER_LABELS.get(param_str, Parameter.VOLUME)
        loop      = bool(msg.get("loop", True))
        tracks    = [int(t) for t in msg.get("tracks", [1])]

        is_tempo = param is Parameter.TEMPO
        depth    = depth_ui  if is_tempo else float(_ui_to_midi(depth_ui))
        center   = center_ui if is_tempo else float(_ui_to_midi(center_ui))

        for t in tracks:
            self._engine.add_lfo(LfoClip(
                track=t, parameter=param, wave=wave,
                rate_ticks=rate_ticks, depth=depth, center_value=center,
                inverted=False, loop=loop,
            ))

    def _lfo_stop(self, lfo_id: int) -> None:
        for lfo in self._engine.lfos:
            if id(lfo) == lfo_id:
                self._engine.remove_lfo(lfo)
                break

    # ── Heartbeat broadcast ────────────────────────────────────────────────────

    async def _broadcast(self) -> None:
        if not self._clients:
            return
        snap = json.dumps(self._snapshot())
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(snap)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(0.2)
            await self._broadcast()

    # ── Startup ────────────────────────────────────────────────────────────────

    async def _serve(self) -> None:
        asyncio.create_task(self._heartbeat())
        config = uvicorn.Config(
            self._app,
            host="0.0.0.0",
            port=PORT,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        await server.serve()

    def start(self) -> None:
        """Launch the server in a background daemon thread. Non-blocking."""
        thread = threading.Thread(
            target=asyncio.run,
            args=(self._serve(),),
            daemon=True,
            name="RemoteServer",
        )
        thread.start()
