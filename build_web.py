"""Generates web/*.html from static/*.html, the single source of truth for the UI.

static/ is the local-server build (server.py + the row editor); web/ is the static-hosting
build (Vercel/Netlify/GitHub Pages) with the same filtering/rendering code minus the features
that need a server to persist anything. Rather than hand-editing both files in parallel
forever, the few intentional differences are marked directly in the static/ source with
WEB:OMIT-START / WEB:OMIT-END comments (using whichever comment syntax is valid at that point -
CSS `/* */`, JS `//`, or HTML `<!-- -->`, including inside a JS template literal that renders to
HTML) and this script strips everything between each marker pair, then applies each page's own
fixed value substitutions (data source URL, the actions-column grid width) that only make sense
because the omitted regions are gone. A page with nothing to strip or substitute (e.g.
reference.html) just passes through unchanged.

Run this after any change to a static/*.html file, before committing:
    python build_web.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
WEB_DIR = ROOT / "web"

OMIT_RE = re.compile(
    r"(?:<!--\s*WEB:OMIT-START[^\n]*?-->|/\*\s*WEB:OMIT-START[^\n]*?\*/|//\s*WEB:OMIT-START[^\n]*)"
    r".*?"
    r"(?:<!--\s*WEB:OMIT-END\s*-->|/\*\s*WEB:OMIT-END\s*\*/|//\s*WEB:OMIT-END)",
    re.DOTALL,
)

# Per-page substitutions, applied after that page's omit blocks are stripped - things that
# differ only because those blocks are gone (a narrower actions column with no Edit button) or
# because this build has no server to fetch from. A page with none (e.g. reference.html) just
# doesn't get an entry here.
SUBSTITUTIONS = {
    "index.html": [
        ('fetch("/api/notes")', 'fetch("./data.json")'),
        ("2.05fr 0.7fr 0.55fr 0.75fr 0.4fr 0.9fr 0.75fr", "2.3fr 0.7fr 0.55fr 0.75fr 0.4fr 0.9fr 0.5fr"),
    ],
}

PAGES = ["index.html", "reference.html"]


def build(name: str) -> str:
    text = (STATIC_DIR / name).read_text(encoding="utf-8")
    text = OMIT_RE.sub("", text)
    for old, new in SUBSTITUTIONS.get(name, []):
        if old not in text:
            raise SystemExit(f"build_web.py: expected substitution target not found in {name}: {old!r}")
        text = text.replace(old, new)
    if "WEB:OMIT" in text:
        raise SystemExit(f"build_web.py: an unmatched WEB:OMIT marker survived in {name} - check pairing in static/{name}")
    return text


def main():
    for name in PAGES:
        out_path = WEB_DIR / name
        out_path.write_text(build(name), encoding="utf-8")
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
