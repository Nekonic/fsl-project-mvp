import sys
from pathlib import Path
from xml.etree import ElementTree

SVG = "http://www.w3.org/2000/svg"
SIZE = 60
VIEW = 300
STROKE = 16
CORNER = 22
PAPER = "#fffefe"
COLOURS = {"red": "#e3292e", "green": "#109e00", "blue": "#2d67b9", "gray": "#4d4d4d"}
GLYPHS = {"client": "gray", "firewall": "green", "shield": "green", "server": "blue",
          "storage": "blue", "statistics": "gray"}
KALI = "host-kali"
KALI_COLOUR = "red"
DRAGON_INSET = 24
DRAGON_SOURCE = "Kali/Logomark/kali-dragon-black.svg"
PRESS_PACK = "https://gitlab.com/kalilinux/documentation/press-pack"
TRADEMARK = "KALI LINUX™ is a trademark of OffSec."
POLICY = "https://www.kali.org/docs/policy/trademark/"

def named(glyph: str) -> str:
    return f"host-{glyph}"

def framed(colour: str, inside: str) -> str:
    edge = STROKE // 2
    return (f'<svg width="{SIZE}" height="{SIZE}" viewBox="0 0 {VIEW} {VIEW}" xmlns="{SVG}">'
            f'<rect x="{edge}" y="{edge}" width="{VIEW - STROKE}" height="{VIEW - STROKE}" rx="{CORNER}" '
            f'fill="{PAPER}" stroke="{COLOURS[colour]}" stroke-width="{STROKE}"/>{inside}</svg>\n')

def glyph(bundled: str, colour: str) -> str:
    ElementTree.register_namespace("", SVG)
    root = ElementTree.fromstring(bundled)
    paper, frame, *drawn = list(root)
    if paper.get("style") != f"fill:{PAPER}" or frame.get("style") != f"fill:{COLOURS[colour]}" or not drawn:
        raise SystemExit("the bundled symbol is not paper, frame, glyph")
    inside = "".join(ElementTree.tostring(part, encoding="unicode").strip() for part in drawn)
    return f'<g style="{root.get("style", "")}">{inside}</g>'

def dragon(mark: str) -> str:
    opening, mark = "<svg ", mark.strip()
    if not mark.startswith(opening):
        raise SystemExit(f"{DRAGON_SOURCE} no longer starts with {opening!r}")
    size = VIEW - 2 * DRAGON_INSET
    return mark.replace(opening, f'<svg x="{DRAGON_INSET}" y="{DRAGON_INSET}" width="{size}" height="{size}" ', 1)

def notice(commit: str) -> str:
    return (f"{TRADEMARK} {DRAGON_SOURCE} from {PRESS_PACK} at {commit}, unmodified, placed at "
            f"{VIEW - 2 * DRAGON_INSET} of {VIEW} inside a square frame drawn around it. Policy: {POLICY}\n")

def built(bundled_dir: Path, mark: str, commit: str) -> dict[str, str]:
    made = {f"{named(name)}.svg": framed(colour, glyph((bundled_dir / colour / f"{name}.svg").read_text(), colour))
            for name, colour in GLYPHS.items()}
    made[f"{KALI}.svg"] = framed(KALI_COLOUR, dragon(mark))
    made[f"{KALI}.txt"] = notice(commit)
    return made

def bundled_square() -> Path:
    import gns3server
    return Path(gns3server.__file__).resolve().parent / "symbols" / "affinity" / "square"

if __name__ == "__main__":
    if len(sys.argv) != 4 or not sys.argv[2]:
        raise SystemExit("usage: symbols.py <kali-dragon-black.svg> <press-pack commit> <out dir>")
    mark, commit, out = Path(sys.argv[1]).read_text(), sys.argv[2], Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    for name, text in built(bundled_square(), mark, commit).items():
        (out / name).write_text(text)
        print(f"fsl-gns3: built {name}")
