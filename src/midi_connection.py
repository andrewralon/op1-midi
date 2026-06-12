"""
Handles OP-1 Field MIDI port detection and connection.

Returns a single shared mido.open_input() port used by both clock.py and
controller.py.  The OP-1 exposes one combined MIDI in/out port; we open
input for receiving clock and output for sending CC.
"""

import sys

import mido


OP1_KEYWORD = "op-1"  # matched case-insensitively against port names


def is_ble_port(name: str) -> bool:
    """Return True if the port name suggests BLE-MIDI rather than USB.

    On macOS/CoreMIDI, BLE-MIDI ports include 'Bluetooth' in their name
    (e.g. 'OP-1 Bluetooth'), while USB ports do not (e.g. 'OP-1').
    """
    low = name.lower()
    return OP1_KEYWORD in low and "bluetooth" in low


def list_ports() -> tuple[list[str], list[str]]:
    """Return (input_ports, output_ports)."""
    return mido.get_input_names(), mido.get_output_names()


def _find_op1_ports(names: list[str]) -> list[str]:
    return [n for n in names if OP1_KEYWORD in n.lower()]


def _prompt_user(names: list[str], direction: str) -> str | None:
    """Prompt the user to pick a port. Returns None if 'no device' is chosen."""
    print(f"available MIDI {direction} ports:")
    for i, name in enumerate(names):
        print(f"  [{i + 1}] {name}")
    print(f"  [0] no device")
    while True:
        raw = input(f"select {direction} port number (or q to quit): ").strip()
        if raw.lower() in ("q", "quit"):
            sys.exit(0)
        if raw == "0":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]
        print("invalid selection, try again.")


def connect() -> tuple[mido.ports.BaseInput | None, mido.ports.BaseOutput | None]:
    """
    Detect the OP-1 Field and open input+output ports.

    Returns (in_port, out_port). Either element may be None if the user
    chose 'no device' for that direction.
    If exactly one OP-1 port is found it is selected automatically.
    If multiple OP-1 ports are found the user is prompted from the full port list.
    If no OP-1 is found the user is also prompted from the full port list.
    """
    in_names, out_names = list_ports()

    print("available MIDI input ports:")
    for name in in_names:
        print(f"  • {name}")
    print("available MIDI output ports:")
    for name in out_names:
        print(f"  • {name}")

    in_matches = _find_op1_ports(in_names)
    if len(in_matches) == 1:
        in_name = in_matches[0]
        print(f"auto-detected op1 input:  {in_name}")
    else:
        if len(in_matches) > 1:
            print("multiple OP-1 input ports found — manual selection required.")
        else:
            print("op1 not found by name — manual selection required.")
        in_name = _prompt_user(in_names, "input")

    out_matches = _find_op1_ports(out_names)
    if len(out_matches) == 1:
        out_name = out_matches[0]
        print(f"auto-detected op1 output: {out_name}")
    else:
        if len(out_matches) > 1:
            print("multiple OP-1 output ports found — manual selection required.")
        else:
            print("op1 not found by name — manual selection required.")
        out_name = _prompt_user(out_names, "output")

    in_port  = mido.open_input(in_name)   if in_name  is not None else None
    out_port = mido.open_output(out_name) if out_name is not None else None
    return in_port, out_port
