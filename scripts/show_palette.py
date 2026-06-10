"""
Show the current color palette defined in src/ui.py.

Usage (run from project root with venv active):
    source .venv/bin/activate
    python scripts/show_palette.py
"""

import sys
import re

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame


def load_palette(path: str = "src/ui.py") -> list[tuple[str, str]]:
    """Parse color variable definitions from the Colors section of ui.py."""
    palette = []
    in_section = False
    pattern = re.compile(r'^(_\w+)\s*=\s*"(#[0-9a-fA-F]{6})"')
    with open(path) as f:
        for line in f:
            if "# Colors" in line:
                in_section = True
            elif in_section and line.startswith("# OP-1"):
                break
            elif in_section:
                m = pattern.match(line.strip())
                if m:
                    palette.append((m.group(1), m.group(2)))
    return palette


def main() -> None:
    palette = load_palette()
    if not palette:
        print("no colors found — is src/ui.py in the current directory?")
        sys.exit(1)

    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowTitle("Color Palette — src/ui.py")
    win.setStyleSheet("background-color: #1e1e1e;")

    layout = QVBoxLayout(win)
    layout.setSpacing(6)
    layout.setContentsMargins(16, 16, 16, 16)

    for name, hex_val in palette:
        row = QHBoxLayout()
        row.setSpacing(10)

        swatch = QFrame()
        swatch.setFixedSize(48, 28)
        swatch.setStyleSheet(
            f"background-color: {hex_val}; border: 1px solid #444444; border-radius: 4px;"
        )
        row.addWidget(swatch)

        label = QLabel(f"{name}  {hex_val}")
        label.setStyleSheet(
            "color: #d8d8d8; font-size: 12pt; font-weight: bold; font-family: monospace;"
        )
        label.setFixedWidth(300)
        row.addWidget(label)
        row.addStretch()

        layout.addLayout(row)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
