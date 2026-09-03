"""Catalog and tag documents from the public "Holy Grail Mark 6" Google Drive, for the 6
subjects this project scopes to. Two things this does differently from scrape.py/tag_with_gemini.py:

1. No API key/auth needed - it scrapes the AF_initDataCallback JSON blob Google Drive's own
   unauthenticated folder-listing page embeds in its HTML (the same data the web UI itself
   renders from), recursively, one HTTP GET per folder.
2. Tagging is almost entirely rule-based instead of AI-based, because the Drive is already
   curated into `Subject / Prelims|Promos / Year / [School] / .../ filename` - school and year
   come from the folder path, doc_type from the Prelims/Promos folder, and only paper number /
   Questions-vs-Answers need a filename regex (reusing enrich.py's SCHOOL_RE/YEAR_RE/base_of/
   role_of/find_paper_number so the two tagging paths behave consistently).

Usage:
    python scrape_gdrive.py                      # crawl + tag all 6 subjects -> data/gdrive_tagged.json
    python scrape_gdrive.py --out data/foo.json   # custom output path
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

import requests

from enrich import (
    SCHOOL_RE, YEAR_RE, base_of, role_of, find_paper_number,
    SUBJECT_PAPER_LABELS, SUBJ_ABBR, compute_group_id,
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_OUT_PATH = Path(__file__).parent / "data" / "gdrive_tagged.json"

# The 6 subject-root folder IDs this project scopes to, inside "Massive Grail (A Level/IB)"
# (drive.google.com/drive/folders/1gC6GQLgcuoHzwDXtEGzTwvzCz0YsYuwg). Re-derive these by crawling
# one level at a time from the root if the Drive gets reorganized - see AGENTS.md.
SUBJECT_ROOTS = {
    "H2 Mathematics": "1W7PENYXGNU4vLnI1KkSmWYWtPb9MCsPO",
    "H2 Computing": "1jvDxXsNPvtHmcDmBneAT-oluP7kVvpJB",
    "H2 Physics": "1EBFqKeO0LUWkEmkXtyoH2JYodVQBZJXE",
    "H2 Economics": "1xnSQXhGD8op_Kf0vJeX9juMmEWIBa689",
    "H2 Chemistry": "169ON_GV2u95OuGChmVL_Fdww_0z1wozA",
    "H1 General Paper": "1hvW-L_Kp-CQx1nF-PB5ROZf-i8RjUfsG",
}

DOC_MIME_ALLOW = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.document",
}

TYPE_FOLDER_TO_DOCTYPE = {"prelims": "Exam Papers", "promos": "MYEs/CAs/Other Tests"}
TYPE_FOLDER_TO_TOPIC = {"prelims": "Prelim", "promos": "Promo"}
YEAR_FOLDER_RE = re.compile(r"^(19[5-9]\d|20[0-4]\d)$")
ANSWER_ISH_RE = re.compile(
    r"(ans|answer|soln|solution|worked.?solution|suggested.?answer|mark.?scheme|marking.?scheme"
    r"|(?<![A-Za-z0-9])ms(?![A-Za-z0-9]))",
    re.IGNORECASE,
)


# --- crawling -----------------------------------------------------------------------------

def list_folder(folder_id: str, retries: int = 3):
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    html = None
    for attempt in range(retries):
        try:
            html = requests.get(url, headers=HEADERS, timeout=20).text
            break
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
    if html is None:
        return None

    blocks = re.findall(r"AF_initDataCallback\((\{.*?\})\);", html, re.S)
    target = next((b for b in blocks
                   if re.search(r'\[null,"[\w-]{20,}"\],null,null,null,"[\w./-]+"', b)), None)
    if target is None:
        return []

    ids_mime = re.findall(r'\[null,"([\w-]{20,})"\],null,null,null,"([\w./-]+)"', target)
    names_raw = re.findall(r'\[\["([^"]{1,200})",null,1\]\]', target)
    names = []
    for n in names_raw:
        if not names or names[-1] != n:
            names.append(n)

    items = []
    for i, (fid, mime) in enumerate(ids_mime):
        name = names[i] if i < len(names) else "(unknown)"
        items.append({"id": fid, "name": name, "mimeType": mime, "isFolder": mime == FOLDER_MIME})
    return items


def walk(folder_id: str, path: list[str], out: list, delay: float = 0.35):
    items = list_folder(folder_id)
    if items is None:
        print(f"  ! failed to fetch {' / '.join(path)}", flush=True)
        return
    for item in items:
        entry = {"path": path + [item["name"]], "id": item["id"], "isFolder": item["isFolder"],
                  "mimeType": item["mimeType"]}
        out.append(entry)
        if item["isFolder"]:
            time.sleep(delay)
            walk(item["id"], path + [item["name"]], out, delay)


# --- tagging --------------------------------------------------------------------------------

def find_school_in_path(path_segments):
    for seg in path_segments:
        m = SCHOOL_RE.search(seg)
        if m:
            return m.group(1).upper()
    return None


def tag_one(entry: dict, subject: str) -> dict:
    path = entry["path"]  # [Prelims|Promos, Year, ...maybe school/subfolders..., filename]
    filename = path[-1]
    base_name, _ext = os.path.splitext(filename)

    doc_type = TYPE_FOLDER_TO_DOCTYPE.get(path[0].strip().lower()) if path else None

    year = None
    if len(path) > 1 and YEAR_FOLDER_RE.match(path[1].strip()):
        year = path[1].strip()
    if not year:
        m = YEAR_RE.search(filename)
        if m:
            year = m.group(0)

    # school: prefer a folder segment between year and filename, fall back to the filename itself
    mid_segments = path[2:-1]
    school = find_school_in_path(mid_segments) or find_school_in_path([filename])

    original_name = base_name.strip()
    n = find_paper_number("", original_name, subject, original_name)
    label = SUBJECT_PAPER_LABELS.get(subject, {}).get(n) if n else None
    is_answer = bool(ANSWER_ISH_RE.search(original_name))

    # Build a clean paper_info from the pieces already extracted, instead of dumping the raw
    # (often messy) filename in - matches the short "Prelim P1 Answers" style AI-tagged
    # grail.moe entries use, and reuses the same topic word ("Prelim"/"Promo") so Drive entries
    # can land in the exact same group_id as an existing grail.moe group.
    topic_word = TYPE_FOLDER_TO_TOPIC.get(path[0].strip().lower(), path[0]) if path else "Paper"
    paper_info = topic_word
    if n:
        paper_info += f" P{n}"
    if is_answer:
        paper_info += " Answers"

    base = base_of(paper_info)
    role = role_of(paper_info, base)

    # enrich.py's year-resolution regex searches `name` specifically; a lot of these filenames
    # only carry the year via the folder path, not repeated in the text itself, so a future
    # `python enrich.py` re-run would silently null year_resolved unless it's in `name` too.
    name_for_regex = original_name
    if year and not YEAR_RE.search(original_name):
        name_for_regex = f"{year} {original_name}"

    full_path = [subject] + path
    tagged = {
        "id": f"gdrive:{entry['id']}",
        "source": "drive",
        "name": name_for_regex,
        "original_name": original_name,
        "note_url": f"https://drive.google.com/file/d/{entry['id']}/view",
        "download_url": f"https://drive.google.com/file/d/{entry['id']}/view",
        "inline_url": f"https://drive.google.com/file/d/{entry['id']}/view",
        "category": "GCE 'A' Levels",
        "subject": subject,
        "doc_type": doc_type or "Exam Papers",
        "year": year,
        "uploaded_by": None,
        "uploaded_on": None,
        "school": school,
        "paper_info": paper_info,
        "paper_info_base": base,
        "paper_info_role": role,
        "paper_number": n,
        "paper_label": label,
        "year_resolved": year,
        "year_source": "name" if year else None,
        "flagged": False,
        "flag_reason": None,
        "drive_path": " / ".join(full_path),
    }
    tagged["group_id"] = compute_group_id(tagged, base, n)
    subj_abbr = SUBJ_ABBR.get(subject, subject)
    school_prefix = f"{school} " if school else ""
    tail = paper_info or doc_type or ""
    tagged["display_name"] = f"{school_prefix}{year or '-'} {subj_abbr} {tail}".strip()
    return tagged


def crawl_and_tag(subjects: dict[str, str], delay: float) -> list[dict]:
    all_tagged = []
    skipped_mime = 0
    for subject, root_id in subjects.items():
        print(f"=== crawling {subject} ===", flush=True)
        raw = []
        t0 = time.time()
        walk(root_id, [], raw, delay)
        files = [e for e in raw if not e["isFolder"]]
        print(f"{subject}: {len(files)} files, {time.time() - t0:.0f}s", flush=True)
        for e in files:
            if e["mimeType"] not in DOC_MIME_ALLOW:
                skipped_mime += 1
                continue
            # walk() paths are relative to the subject root; tag_one wants [Prelims|Promos, Year, ...]
            all_tagged.append(tag_one({**e, "path": e["path"]}, subject))
    print(f"\n{len(all_tagged)} tagged, {skipped_mime} skipped (non-document mimeType)", flush=True)
    return all_tagged


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    ap.add_argument("--delay", type=float, default=0.35, help="seconds between folder requests")
    args = ap.parse_args()

    tagged = crawl_and_tag(SUBJECT_ROOTS, args.delay)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(tagged, args.out.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
