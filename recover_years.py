"""One-off: recover a year for flagged entries with no determinable year, by reading the PDF's
own cover-page text - most exam paper PDFs aren't scanned images and state the year plainly. See
AGENTS.md's "Known data-quality patterns" section for the technique and its trap (CSQ papers
quote real news articles with unrelated years - only trust a year found near a strong
institutional signal, not just anywhere on the page).

Writes results to a JSON file: {id: recovered_year or null}. Does not touch data/tagged.json -
applying a recovered year goes through `name` (see AGENTS.md), done as a separate step so the
recovery pass can be reviewed before it's applied.
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

import requests
from pypdf import PdfReader

YEAR_RE = re.compile(r"(?<![A-Za-z0-9])(19[5-9]\d|20[0-4]\d)(?![A-Za-z0-9])")
SIGNAL_RE = re.compile(
    r"PRELIMINARY EXAM|PROMOTION EXAM|PROMOTIONAL EXAM|\xa9\s*[A-Za-z]|"
    r"\b\d{4}/0[1-9]\b",  # syllabus-code pattern like 9732/02
    re.IGNORECASE,
)


def recover_year(url: str) -> str | None:
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        reader = PdfReader(BytesIO(r.content))
        text = ""
        for page in reader.pages[:2]:
            text += page.extract_text() or ""
    except Exception as exc:
        print(f"    error: {exc}", file=sys.stderr)
        return None

    for m in YEAR_RE.finditer(text):
        window = text[max(0, m.start() - 80):m.end() + 80]
        if SIGNAL_RE.search(window):
            return m.group(0)
    return None


def main():
    in_path, out_path = sys.argv[1], sys.argv[2]
    targets = json.load(open(in_path, encoding="utf-8"))
    results = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(recover_year, t["url"]): t["id"] for t in targets}
        for fut in as_completed(futures):
            tid = futures[fut]
            year = fut.result()
            results[tid] = year
            print(f"  {tid}: {year}", flush=True)

    json.dump(results, open(out_path, "w", encoding="utf-8"), indent=1)
    n_found = sum(1 for v in results.values() if v)
    print(f"\nDone. {n_found}/{len(results)} years recovered.")


if __name__ == "__main__":
    main()
