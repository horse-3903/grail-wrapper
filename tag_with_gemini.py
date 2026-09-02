"""Tag scraped grail.moe notes using the free Gemini API, as an unattended alternative
to dispatching the note-tagger Claude Code subagent interactively.

Get a free API key at https://aistudio.google.com/apikey, then either put it in a local
.env file (GEMINI_API_KEY=your-key-here, gitignored) or set it directly:
    setx GEMINI_API_KEY "your-key-here"      (Windows, new shells)
    $env:GEMINI_API_KEY = "your-key-here"    (current PowerShell session)
    export GEMINI_API_KEY=your-key-here      (bash)

Usage:
    python tag_with_gemini.py               # tag every entry in data/tagged.json missing school+paper_info
    python tag_with_gemini.py --in data/raw.json --out data/raw.json   # tag a fresh scrape in place
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = "gemini-3.6-flash"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

BATCH_SIZE = 150

PROMPT = """You are tagging metadata for Singapore JC 'A' Level exam paper library entries.

For each entry below, infer from the freeform `name` field (examples: "ACJC 2019 H2 Math Prelim",
"CJC 2019 A level H2 Physics Answers", "RVHS 2022 H2 Econs P1 Answers", "Compilation TYS 2015-2020 H2 Chem"):

- school: the JC/institution abbreviation mentioned in the name (ACJC, CJC, RVHS, NJC, HCI, VJC,
  TMJC, YJC, SAJC, MI, NYJC, ASRJC, EJC, JPJC, DHS, RI, IJC, PJC, JJC, TPJC, MJC, XJC, RJC). Use
  the abbreviation as written in the name, uppercased. null if the name is a compilation, a user
  mock paper, or no school is identifiable.
- paper_info: a short descriptor beyond doc_type, e.g. "Prelim P1", "Promo", "TYS Compilation",
  "Answers" (combine where relevant, e.g. "Prelim P1 Answers"). null if nothing more specific
  than doc_type is stated in the name.
- flagged / flag_reason: true with a one-sentence reason when the name looks inconsistent with
  the structured fields (a year mentioned in the name differs from the year field, the name
  references a different subject level than subject, or the doc_type looks mismatched). Otherwise
  false, and omit flag_reason.

Entries:
{entries_json}

Output a JSON array, one object per entry, same ids and same order as the input, with exactly
these fields: id, school, paper_info, flagged, flag_reason."""

RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "id": {"type": "STRING"},
            "school": {"type": "STRING", "nullable": True},
            "paper_info": {"type": "STRING", "nullable": True},
            "flagged": {"type": "BOOLEAN"},
            "flag_reason": {"type": "STRING", "nullable": True},
        },
        "required": ["id", "school", "paper_info", "flagged"],
    },
}


def tag_batch(entries: list[dict], retries: int = 4) -> list[dict] | None:
    payload = [
        {
            "id": e["id"],
            "name": e.get("original_name") or e["name"],
            "subject": e.get("subject"),
            "year": e.get("year"),
            "doc_type": e.get("doc_type"),
        }
        for e in entries
    ]
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(entries_json=json.dumps(payload, ensure_ascii=False))}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }

    for attempt in range(retries):
        try:
            r = requests.post(API_URL, params={"key": API_KEY}, json=body, timeout=90)
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
            continue

        if r.status_code == 200:
            try:
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                print(f"    could not parse response: {exc}", flush=True)
                return None
        if r.status_code == 429:
            print(f"    rate limited, backing off...", flush=True)
            time.sleep(25 * (attempt + 1))
            continue
        print(f"    HTTP {r.status_code}: {r.text[:200]}", flush=True)
        time.sleep(5 * (attempt + 1))

    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="in_path", type=Path, default=Path("data/tagged.json"))
    ap.add_argument("--out", dest="out_path", type=Path, default=None, help="defaults to --in (in place)")
    ap.add_argument("--force", action="store_true", help="re-tag entries that already have tags")
    ap.add_argument("--include-flagged", action="store_true", help="also re-tag entries currently flagged for review")
    ap.add_argument("--no-backup", action="store_true", help="skip archiving out_path before overwriting it")
    args = ap.parse_args()
    out_path = args.out_path or args.in_path

    if not API_KEY:
        sys.exit("Set GEMINI_API_KEY first (free key at https://aistudio.google.com/apikey)")

    if out_path.exists() and not args.no_backup:
        backup_dir = Path("data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{out_path.stem}_{stamp}{out_path.suffix}"
        backup_path.write_bytes(out_path.read_bytes())
        print(f"Backed up {out_path} -> {backup_path}", flush=True)

    data = json.load(open(args.in_path, encoding="utf-8"))
    if args.force:
        todo = data
    else:
        todo = [
            e for e in data
            if (e.get("school") is None and e.get("paper_info") is None)
            or (args.include_flagged and e.get("flagged"))
        ]
    print(f"{len(data)} entries total, {len(todo)} to tag", flush=True)

    by_id = {e["id"]: e for e in data}
    n_tagged = 0
    n_failed_batches = 0
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i : i + BATCH_SIZE]
        print(f"  batch {i // BATCH_SIZE + 1}/{-(-len(todo) // BATCH_SIZE)} ({len(batch)} entries)...", flush=True)
        result = tag_batch(batch)
        if result is None:
            n_failed_batches += 1
            continue
        for tag in result:
            entry = by_id.get(tag.get("id"))
            if not entry:
                continue
            entry["school"] = tag.get("school")
            entry["paper_info"] = tag.get("paper_info")
            entry["flagged"] = bool(tag.get("flagged"))
            entry["flag_reason"] = tag.get("flag_reason") if entry["flagged"] else None
            n_tagged += 1

        tmp = out_path.with_suffix(".tmp")
        json.dump(list(by_id.values()), tmp.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
        tmp.replace(out_path)

    print(f"\nDone. {n_tagged} entries tagged, {n_failed_batches} batches failed.", flush=True)


if __name__ == "__main__":
    main()
