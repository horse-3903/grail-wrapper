"""Local wrapper server for the Holy Grail library index.

Serves the scraped+tagged index. PDF links point straight at grail.moe's static
document URLs (inline_url) - no local download/caching proxy.
"""
import json
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from enrich import SUBJ_ABBR, SUBJECT_PAPER_LABELS, base_of, role_of

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "tagged.json"
RAW_PATH = ROOT / "data" / "raw.json"
MANUAL_GROUPS_PATH = ROOT / "data" / "manual_groups.json"
BACKUP_DIR = ROOT / "data" / "backups"

EDITABLE_NOTE_FIELDS = {"school", "paper_info", "subject", "doc_type", "year_resolved", "paper_number", "group_id"}

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


def backup_tagged():
    if not DATA_PATH.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"tagged_{stamp}.json"
    backup_path.write_bytes(DATA_PATH.read_bytes())


def save_tagged(entries):
    backup_tagged()
    tmp = DATA_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    tmp.replace(DATA_PATH)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/notes")
def api_notes():
    return jsonify(load_index())


@app.route("/api/note/<note_id>", methods=["PATCH"])
def api_update_note(note_id):
    """Edits one entry's metadata/grouping in place. Backs up data/tagged.json first."""
    body = request.get_json(force=True, silent=True) or {}
    updates = {k: v for k, v in body.items() if k in EDITABLE_NOTE_FIELDS}
    if not updates:
        return jsonify({"error": "no editable fields provided"}), 400

    if not DATA_PATH.exists():
        return jsonify({"error": "data/tagged.json not found"}), 404
    with DATA_PATH.open(encoding="utf-8") as f:
        entries = json.load(f)

    entry = next((e for e in entries if e["id"] == note_id), None)
    if entry is None:
        return jsonify({"error": "note not found"}), 404

    for key, value in updates.items():
        if key == "paper_number":
            try:
                entry[key] = int(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                return jsonify({"error": "paper_number must be a number"}), 400
        else:
            entry[key] = value or None

    # a manually-set group_id shouldn't be silently overwritten by a future `python enrich.py`
    # run, so it gets the same "manual|" protection the answer-linker subagent's groups use
    if "group_id" in updates:
        gid = entry.get("group_id") or ""
        if gid and not gid.startswith("manual|") and not gid.startswith("linked|"):
            entry["group_id"] = f"manual|{gid}"

    base = base_of(entry.get("paper_info"))
    entry["paper_info_base"] = base
    entry["paper_info_role"] = role_of(entry.get("paper_info"), base)
    if "paper_number" in updates or "subject" in updates:
        entry["paper_label"] = SUBJECT_PAPER_LABELS.get(entry.get("subject"), {}).get(entry.get("paper_number"))
    subj_abbr = SUBJ_ABBR.get(entry.get("subject"), entry.get("subject") or "")
    school_prefix = f"{entry['school']} " if entry.get("school") else ""
    tail = entry.get("paper_info") or entry.get("doc_type") or ""
    entry["display_name"] = f"{school_prefix}{entry.get('year_resolved') or '-'} {subj_abbr} {tail}".strip()

    save_tagged(entries)
    return jsonify(entry)


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


if __name__ == "__main__":
    app.run(port=8765, debug=False)
