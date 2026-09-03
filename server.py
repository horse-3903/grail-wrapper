"""Local wrapper server for the Holy Grail library index.

Serves the scraped+tagged index. PDF links point straight at grail.moe's static
document URLs (inline_url) - no local download/caching proxy.
"""
import json
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from enrich import SUBJ_ABBR, SUBJECT_PAPER_LABELS, base_of, compute_group_id, find_paper_number, role_of

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "tagged.json"
RAW_PATH = ROOT / "data" / "raw.json"
MANUAL_GROUPS_PATH = ROOT / "data" / "manual_groups.json"
BACKUP_DIR = ROOT / "data" / "backups"

# Grouping is handled by the dedicated merge/ungroup endpoints below, not this generic PATCH -
# a raw group_id text field is neither easy to discover nor safe to hand-edit (see api_merge_note).
EDITABLE_NOTE_FIELDS = {"school", "paper_info", "subject", "doc_type", "year_resolved", "paper_number"}

app = Flask(__name__, static_folder="static", static_url_path="")


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


@app.route("/api/note/<note_id>/merge", methods=["POST"])
def api_merge_note(note_id):
    """Merges one entry into an existing group (picked from the UI's search results, so
    target_group_id is always a real, currently-in-use group_id - never hand-typed).

    If the target group isn't already protected (manual|/linked|), the whole group - every
    current member, not just this entry - gets moved onto a manual|-prefixed id. Doing it to
    the whole group, not just the newly added entry, is what keeps them grouped together after
    a future `python enrich.py` run: enrich.py recomputes group_id for any entry that isn't
    already manual|/linked|-prefixed, so if only the new entry were protected it would keep a
    different id than its now-unprotected groupmates and immediately fall back out of the group.
    """
    body = request.get_json(force=True, silent=True) or {}
    target_gid = body.get("target_group_id")
    if not target_gid:
        return jsonify({"error": "target_group_id required"}), 400

    if not DATA_PATH.exists():
        return jsonify({"error": "data/tagged.json not found"}), 404
    with DATA_PATH.open(encoding="utf-8") as f:
        entries = json.load(f)

    entry = next((e for e in entries if e["id"] == note_id), None)
    if entry is None:
        return jsonify({"error": "note not found"}), 404
    if not any(e.get("group_id") == target_gid for e in entries):
        return jsonify({"error": "target group not found"}), 404

    if not (target_gid.startswith("manual|") or target_gid.startswith("linked|")):
        protected_gid = f"manual|{target_gid}"
        for e in entries:
            if e.get("group_id") == target_gid:
                e["group_id"] = protected_gid
        target_gid = protected_gid

    entry["group_id"] = target_gid
    save_tagged(entries)
    return jsonify({"entries": entries})


@app.route("/api/note/<note_id>/ungroup", methods=["POST"])
def api_ungroup_note(note_id):
    """Splits one entry back out into its own natural group - the same group_id `python
    enrich.py` would give it standing alone, so it may still land next to school/year/subject
    peers on its own merits, just without the manual override that was pinning it elsewhere.
    """
    if not DATA_PATH.exists():
        return jsonify({"error": "data/tagged.json not found"}), 404
    with DATA_PATH.open(encoding="utf-8") as f:
        entries = json.load(f)

    entry = next((e for e in entries if e["id"] == note_id), None)
    if entry is None:
        return jsonify({"error": "note not found"}), 404

    base = base_of(entry.get("paper_info"))
    n = find_paper_number(base, entry.get("original_name", entry["name"]), entry.get("subject"), entry.get("paper_info"))
    entry["group_id"] = compute_group_id(entry, base, n)
    save_tagged(entries)
    return jsonify({"entries": entries})


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
