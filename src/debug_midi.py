"""
Diagnostic: print every MIDI message arriving from the OP-1 (clock ticks omitted).

Run with:
    python -m src.debug_midi

Then move controls on the OP-1 (volume, pan, mute) and watch what messages appear.
Press Ctrl-C to stop.
"""

import mido
from src.midi_connection import list_ports, _find_op1


def main() -> None:
    in_names, _ = list_ports()

    in_name = _find_op1(in_names)
    if not in_name:
        print("op1 not found by name. available ports:")
        for p in in_names:
            print(f"  {p}")
        return

    print(f"listening on: {in_name}")
    print("move controls on the op1 — ctrl-c to stop\n")

    with mido.open_input(in_name) as port:
        for msg in port:
            if msg.type == "clock":
                continue          # skip 24-per-beat clock flood
            if msg.type == "active_sensing":
                continue          # skip keepalive chatter
            print(msg, flush=True)


if __name__ == "__main__":
    main()
