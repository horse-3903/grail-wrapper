"""Merge a tagged Google Drive catalog (from scrape_gdrive.py) into data/tagged.json, adding
only papers not already covered by the grail.moe-sourced data.

"Covered" means an entry already exists with the same (school, year_resolved, subject,
paper_number, Questions-vs-Answers) - checked first within the same group_id, then loosened to
the whole (school, year_resolved, subject) in case the topic word differs slightly. Among the
Drive files that aren't covered, near-duplicate re-uploads of the same paper (same group_id +
paper_number + role) are deduplicated down to one representative (shortest original_name).

Usage:
    python scrape_gdrive.py                 # -> data/gdrive_tagged.json
    python merge_gdrive.py                  # merges data/gdrive_tagged.json into data/tagged.json
"""
import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

DEFAULT_DRIVE_PATH = Path(__file__).parent / "data" / "gdrive_tagged.json"
DEFAULT_TAGGED_PATH = Path(__file__).parent / "data" / "tagged.json"


def _role(e: dict) -> str:
    r = (e.get("paper_info_role") or "").lower()
    return "Answers" if ("answer" in r or "solution" in r or "mark scheme" in r) else "Questions"


def find_gaps(drive: list[dict], existing: list[dict]) -> list[dict]:
    existing_by_group = defaultdict(set)
    existing_by_ssy = defaultdict(set)
    for e in existing:
        sig = (e.get("paper_number"), _role(e))
        existing_by_group[e["group_id"]].add(sig)
        existing_by_ssy[(e.get("school"), e.get("year_resolved"), e.get("subject"))].add(sig)

    gaps = []
    for d in drive:
        sig = (d.get("paper_number"), _role(d))
        if sig in existing_by_group.get(d["group_id"], set()):
            continue
        if sig in existing_by_ssy.get((d.get("school"), d.get("year_resolved"), d.get("subject")), set()):
            continue
        gaps.append(d)
    return gaps


def dedupe(gaps: list[dict]) -> list[dict]:
    clusters = defaultdict(list)
    for g in gaps:
        sig = (g["group_id"], g.get("paper_number"), _role(g))
        clusters[sig].append(g)
    return [min(members, key=lambda e: (len(e["original_name"]), e["id"]))
            for members in clusters.values()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drive", type=Path, default=DEFAULT_DRIVE_PATH)
    ap.add_argument("--tagged", type=Path, default=DEFAULT_TAGGED_PATH)
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    drive = json.load(args.drive.open(encoding="utf-8"))
    existing = json.load(args.tagged.open(encoding="utf-8"))

    gaps = find_gaps(drive, existing)
    deduped = dedupe(gaps)
    print(f"{len(drive)} drive files, {len(gaps)} not already covered, "
          f"{len(deduped)} after dropping {len(gaps) - len(deduped)} redundant re-uploads")

    if not deduped:
        print("nothing to merge")
        return

    if args.tagged.exists() and not args.no_backup:
        backup_dir = Path("data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"tagged_{stamp}.json"
        backup_path.write_bytes(args.tagged.read_bytes())
        print(f"backed up {args.tagged} -> {backup_path}")

    merged = existing + deduped
    json.dump(merged, args.tagged.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(existing)} existing + {len(deduped)} new = {len(merged)} total, saved {args.tagged}")
    print("run `python enrich.py` next, then sync web/data.json")


if __name__ == "__main__":
    main()
