"""Local wrapper server for the Holy Grail library index.

Serves the scraped+tagged index. PDF links point straight at grail.moe's static
document URLs (inline_url) - no local download/caching proxy.
"""
import json
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from enrich import SUBJ_ABBR, SUBJECT_PAPER_LABELS, base_of, compute_group_id, find_paper_number, role_of

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "data" / "tagged.json"
RAW_PATH = ROOT / "data" / "raw.json"
BACKUP_DIR = ROOT / "data" / "backups"

# Grouping is handled by the dedicated merge/ungroup endpoints below, not this generic PATCH -
# a raw group_id text field is neither easy to discover nor safe to hand-edit (see api_merge_note).
EDITABLE_NOTE_FIELDS = {"school", "paper_info", "subject", "doc_type", "year_resolved", "paper_number"}

app = Flask(__name__, static_folder="static", static_url_path="")


class NotFound(Exception):
    """A 404 with a JSON body, for load_entry() below - Flask's built-in abort(404) would
    otherwise render an HTML error page, which the frontend's fetch().then(r => r.json())
    calls can't parse.
    """
    def __init__(self, message):
        super().__init__(message)
        self.message = message


@app.errorhandler(NotFound)
def handle_not_found(exc):
    return jsonify({"error": exc.message}), 404


def load_index():
    path = DATA_PATH if DATA_PATH.exists() else RAW_PATH
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_entry(note_id):
    """Loads data/tagged.json and finds one entry by id - the read-modify-write starting
    point shared by every endpoint below that edits a single note. Raises NotFound (a) if
    data/tagged.json doesn't exist yet, or (b) if no entry has this id, so callers don't
    each need their own existence checks.
    """
    if not DATA_PATH.exists():
        raise NotFound("data/tagged.json not found")
    with DATA_PATH.open(encoding="utf-8") as f:
        entries = json.load(f)
    entry = next((e for e in entries if e["id"] == note_id), None)
    if entry is None:
        raise NotFound("note not found")
    return entries, entry


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

    entries, entry = load_entry(note_id)

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
    target_group_id is always a real, currently-in-use group_id - never hand-typed). This is
    the only grouping mechanism this server exposes: group_id is written directly onto each
    entry in data/tagged.json rather than kept in a separate overlay file, so there is exactly
    one place ("what's this entry's group_id right now") to reason about.

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

    entries, entry = load_entry(note_id)
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
    entries, entry = load_entry(note_id)

    base = base_of(entry.get("paper_info"))
    n = find_paper_number(base, entry.get("original_name", entry["name"]), entry.get("subject"), entry.get("paper_info"))
    entry["group_id"] = compute_group_id(entry, base, n)
    save_tagged(entries)
    return jsonify({"entries": entries})


if __name__ == "__main__":
    app.run(port=8765, debug=False)
