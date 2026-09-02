"""Local wrapper server for the Holy Grail library index.

Serves the scraped+tagged index and proxies PDF downloads on demand,
caching them under downloads/ so repeat opens are instant and offline.
"""
import json
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, send_from_directory, stream_with_context

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "tagged.json"
RAW_PATH = ROOT / "data" / "raw.json"
CACHE_DIR = ROOT / "downloads"
CACHE_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static")


def load_index():
    path = DATA_PATH if DATA_PATH.exists() else RAW_PATH
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/notes")
def api_notes():
    return jsonify(load_index())


@app.route("/api/download/<note_id>")
def api_download(note_id):
    cached = CACHE_DIR / f"{note_id}.pdf"
    if cached.exists():
        return send_from_directory(CACHE_DIR, f"{note_id}.pdf", mimetype="application/pdf")

    upstream = requests.get(
        f"https://api.grail.moe/note/download/{note_id}", stream=True, timeout=30
    )
    if upstream.status_code != 200:
        return jsonify({"error": f"upstream returned {upstream.status_code}"}), 502

    with cached.open("wb") as f:
        for chunk in upstream.iter_content(chunk_size=65536):
            f.write(chunk)

    return send_from_directory(CACHE_DIR, f"{note_id}.pdf", mimetype="application/pdf")


if __name__ == "__main__":
    app.run(port=8765, debug=False)
