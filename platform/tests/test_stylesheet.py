import pathlib
import re

CONSOLE = pathlib.Path(__file__).resolve().parent.parent / "console/templates/console"
STYLESHEET = CONSOLE / "tailwind.css"

HOOKS = {"alert-row", "chip", "fire", "lift", "start", "tab"}
BLOCKS = {"body_class", "main_class", "nav_class", "endblock"}

def templates():
    return sorted(CONSOLE.glob("*.html"))

def selector(token):
    return "." + re.sub(r"([.:/\[\]%()])", r"\\\1", token)

def utilities():
    found = set()
    for path in templates():
        for chunk in re.findall(
            r'class(?:Name)?\s*=\s*["`\']([^"`\']*)["`\']', path.read_text()
        ):
            for token in chunk.split():
                if re.fullmatch(r"[a-z0-9:/\[\]._%-]+", token):
                    found.add(token)
    return found - HOOKS - BLOCKS

def test_the_console_fetches_nothing_from_the_internet():
    outside = {
        path.name: sorted(set(re.findall(r'(?:src|href)="(https?://[^"]+)"', path.read_text())))
        for path in templates()
    }
    outside = {name: urls for name, urls in outside.items() if urls}

    assert outside == {}, (
        f"the console loads {outside} at render time. A range is isolated by "
        f"the time it matters, and an operator would meet it unstyled"
    )

def test_every_utility_the_console_uses_is_in_the_stylesheet():
    css = STYLESHEET.read_text()
    missing = sorted(token for token in utilities() if selector(token) not in css)

    assert missing == [], (
        f"{missing} are used and not built, so they do nothing on screen. The "
        f"stylesheet is generated from these templates: run bin/build-css"
    )

def test_the_stylesheet_is_safe_to_inline_into_a_template():
    css = STYLESHEET.read_text()

    assert "{{" not in css and "{%" not in css, (
        "the stylesheet is included into base.html, so Django renders it as a "
        "template; a brace pair in the CSS would be read as a tag"
    )

def test_the_stylesheet_is_actually_built_and_not_a_placeholder():
    css = STYLESHEET.read_text()

    assert len(css) > 5000 and ".text-slate-200" in css
