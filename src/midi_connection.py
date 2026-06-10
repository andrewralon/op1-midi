"""
Handles OP-1 Field MIDI port detection and connection.

Returns a single shared mido.open_input() port used by both clock.py and
controller.py.  The OP-1 exposes one combined MIDI in/out port; we open
input for receiving clock and output for sending CC.
"""

import sys

import mido


OP1_KEYWORD = "op-1"  # matched case-insensitively against port names


def list_ports() -> tuple[list[str], list[str]]:
    """Return (input_ports, output_ports)."""
    return mido.get_input_names(), mido.get_output_names()


def _find_op1(names: list[str]) -> str | None:
    for name in names:
        if OP1_KEYWORD in name.lower():
            return name
    return None


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
    If auto-detection fails the user is prompted to choose manually.
    """
    in_names, out_names = list_ports()

    print("available MIDI input ports:")
    for name in in_names:
        print(f"  • {name}")
    print("available MIDI output ports:")
    for name in out_names:
        print(f"  • {name}")

    in_name = _find_op1(in_names)
    if in_name:
        print(f"auto-detected op1 input:  {in_name}")
    else:
        print("op1 not found by name — manual selection required.")
        in_name = _prompt_user(in_names, "input")

    out_name = _find_op1(out_names)
    if out_name:
        print(f"auto-detected op1 output: {out_name}")
    else:
        out_name = _prompt_user(out_names, "output")

    in_port  = mido.open_input(in_name)   if in_name  is not None else None
    out_port = mido.open_output(out_name) if out_name is not None else None
    return in_port, out_port
