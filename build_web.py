"""Generates web/index.html from static/index.html, the single source of truth for the UI.

static/index.html is the local-server build (server.py + the row editor); web/index.html is
the static-hosting build (Vercel/Netlify/GitHub Pages) with the same filtering/rendering code
minus the features that need a server to persist anything. Rather than hand-editing both files
in parallel forever, the few intentional differences are marked directly in static/index.html
with WEB:OMIT-START / WEB:OMIT-END comments (using whichever comment syntax is valid at that
point - CSS `/* */`, JS `//`, or HTML `<!-- -->`, including inside a JS template literal that
renders to HTML) and this script strips everything between each marker pair, then applies the
couple of fixed value substitutions (data source URL, the actions-column grid width) that only
make sense because the omitted regions are gone.

Run this after any change to static/index.html, before committing:
    python build_web.py
"""
import re
from pathlib import Path

STATIC_PATH = Path(__file__).parent / "static" / "index.html"
WEB_PATH = Path(__file__).parent / "web" / "index.html"

OMIT_RE = re.compile(
    r"(?:<!--\s*WEB:OMIT-START[^\n]*?-->|/\*\s*WEB:OMIT-START[^\n]*?\*/|//\s*WEB:OMIT-START[^\n]*)"
    r".*?"
    r"(?:<!--\s*WEB:OMIT-END\s*-->|/\*\s*WEB:OMIT-END\s*\*/|//\s*WEB:OMIT-END)",
    re.DOTALL,
)

# Applied after the omit blocks are stripped - things that differ only because those blocks
# are gone (a narrower actions column with no Edit button) or because this build has no
# server to fetch from.
SUBSTITUTIONS = [
    ('fetch("/api/notes")', 'fetch("./data.json")'),
    ("2.05fr 0.7fr 0.55fr 0.75fr 0.4fr 0.9fr 0.75fr", "2.3fr 0.7fr 0.55fr 0.75fr 0.4fr 0.9fr 0.5fr"),
]


def build() -> str:
    text = STATIC_PATH.read_text(encoding="utf-8")
    text = OMIT_RE.sub("", text)
    for old, new in SUBSTITUTIONS:
        if old not in text:
            raise SystemExit(f"build_web.py: expected substitution target not found: {old!r}")
        text = text.replace(old, new)
    if "WEB:OMIT" in text:
        raise SystemExit("build_web.py: an unmatched WEB:OMIT marker survived - check pairing in static/index.html")
    return text


def main():
    WEB_PATH.write_text(build(), encoding="utf-8")
    print(f"Wrote {WEB_PATH}")


if __name__ == "__main__":
    main()
