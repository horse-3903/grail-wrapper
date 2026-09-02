"""Local wrapper server for the Holy Grail library index.

Serves the scraped+tagged index and proxies PDF downloads on demand,
caching them under downloads/ so repeat opens are instant and offline.
"""
import json
import uuid
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "tagged.json"
RAW_PATH = ROOT / "data" / "raw.json"
MANUAL_GROUPS_PATH = ROOT / "data" / "manual_groups.json"
CACHE_DIR = ROOT / "downloads"
CACHE_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static")


def load_manual_groups():
    if not MANUAL_GROUPS_PATH.exists():
        return []
    with MANUAL_GROUPS_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def save_manual_groups(groups):
    MANUAL_GROUPS_PATH.parent.mkdir(exist_ok=True)
    with MANUAL_GROUPS_PATH.open("w", encoding="utf-8") as f:
        json.dump(groups, f, ensure_ascii=False, indent=1)


def load_index():
    path = DATA_PATH if DATA_PATH.exists() else RAW_PATH
    with path.open(encoding="utf-8") as f:
        entries = json.load(f)

    by_id = {e["id"]: e for e in entries}
    for g in load_manual_groups():
        gid = f"manual|{g['id']}"
        for member_id in g["members"]:
            if member_id in by_id:
                by_id[member_id]["group_id"] = gid

    return list(by_id.values())


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/notes")
def api_notes():
    return jsonify(load_index())


@app.route("/api/manual-group", methods=["POST"])
def api_manual_group():
    body = request.get_json(force=True)
    members = body.get("members") or []
    if len(members) < 2:
        return jsonify({"error": "need at least 2 members"}), 400

    groups = load_manual_groups()
    new_group = {"id": uuid.uuid4().hex[:8], "members": members, "label": body.get("label", "")}
    groups.append(new_group)
    save_manual_groups(groups)
    return jsonify(new_group)


@app.route("/api/manual-group/<group_id>", methods=["DELETE"])
def api_manual_ungroup(group_id):
    groups = load_manual_groups()
    remaining = [g for g in groups if g["id"] != group_id]
    if len(remaining) == len(groups):
        return jsonify({"error": "group not found"}), 404
    save_manual_groups(remaining)
    return jsonify({"ok": True})


@app.route("/api/download/<note_id>")
def api_download(note_id):
    cached = CACHE_DIR / f"{note_id}.pdf"
    if cached.exists():
        return send_from_directory(CACHE_DIR, f"{note_id}.pdf", mimetype="application/pdf")

    # inline_url (document.grail.moe, stable CloudFront link) skips the extra redirect
    # through api.grail.moe's short-lived presigned S3 URL when we already know it
    entry = next((e for e in load_index() if e["id"] == note_id), None)
    fetch_url = (entry and entry.get("inline_url")) or f"https://api.grail.moe/note/download/{note_id}"

    upstream = requests.get(fetch_url, stream=True, timeout=30)
    if upstream.status_code != 200:
        return jsonify({"error": f"upstream returned {upstream.status_code}"}), 502

    with cached.open("wb") as f:
        for chunk in upstream.iter_content(chunk_size=65536):
            f.write(chunk)

    return send_from_directory(CACHE_DIR, f"{note_id}.pdf", mimetype="application/pdf")


if __name__ == "__main__":
    app.run(port=8765, debug=False)
