"""Render agents/orchestrator/dona-salvia-hero.txt (one character per pixel) into banner_hero of the Dona Sálvia skin.

Each terminal cell is an upper half block whose foreground is the top pixel and whose background is the bottom one, so
the art keeps square pixels. Transparent cells are U+2800 (braille blank), never spaces: Rich strips trailing spaces
before centering each row of the banner's left column, which pushes rows of different widths out of line.

    python3 scripts/render_hero.py
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "agents/orchestrator/dona-salvia-hero.txt"
SKIN = REPO / "agents/orchestrator/skins/dona-salvia.yaml"
BLANK = "⠀"


def cell(top: str | None, bottom: str | None) -> tuple[str, str]:
    """(Rich style, character) of one terminal cell made of a top and a bottom pixel colour."""
    if top is None and bottom is None:
        return "", BLANK
    if top is None:
        return bottom, "▄"
    if bottom is None:
        return top, "▀"
    return (top, "█") if top == bottom else (f"{top} on {bottom}", "▀")


def render(art: str) -> str:
    palette, rows = {}, []
    for line in art.splitlines():
        if re.fullmatch(r"\S #[0-9A-Fa-f]{6}", line):
            palette[line[0]] = line[2:].upper()
        elif line and not line.startswith("#"):
            rows.append(line)
    assert rows and len(rows) % 2 == 0 and len({len(row) for row in rows}) == 1, "the art needs an even number of equal rows"
    unknown = set("".join(rows)) - set(palette) - {"."}
    assert not unknown, f"pixels without a palette colour: {sorted(unknown)}"
    lines = []
    for top_row, bottom_row in zip(rows[::2], rows[1::2]):
        cells = [cell(palette.get(top), palette.get(bottom)) for top, bottom in zip(top_row, bottom_row)]
        line, start = "", 0
        while start < len(cells):
            end = start
            while end < len(cells) and cells[end][0] == cells[start][0]:
                end += 1
            text = "".join(character for _, character in cells[start:end])
            line += f"[{cells[start][0]}]{text}[/]" if cells[start][0] else text
            start = end
        lines.append(line)
    return "\n".join(lines)


def main() -> None:
    head, marker, _ = SKIN.read_text().partition("\nbanner_hero:")
    assert marker, f"{SKIN} has no banner_hero key"
    SKIN.write_text(head + "\nbanner_hero: |-\n" + "".join(f"  {line}\n" for line in render(ART.read_text()).splitlines()))


if __name__ == "__main__":
    main()
