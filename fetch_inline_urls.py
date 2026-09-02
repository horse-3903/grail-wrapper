"""Fetch each note's detail page to grab the stable document.grail.moe PDF URL.

The listing pages (used by scrape.py) only carry the api.grail.moe/note/download/{id}
redirect link, which forces a download (Content-Disposition: attachment baked into a
presigned, expiring S3 URL). Each note's own detail page also links a second, stable
CloudFront URL (document.grail.moe/<hash>.pdf) with no Content-Disposition header, so
it opens inline in the browser instead. This script fills in that field for every
entry in data/tagged.json.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

DATA_PATH = Path(__file__).parent / "data" / "tagged.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (grail-local-index-scraper)"}
INLINE_URL_RE = re.compile(r"https://document\.grail\.moe/[a-f0-9]+\.pdf")


def fetch_inline_url(note_url: str) -> str | None:
    for attempt in range(3):
        try:
            r = requests.get(note_url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                m = INLINE_URL_RE.search(r.text)
                return m.group(0) if m else None
        except requests.RequestException:
            pass
        time.sleep(0.8 * (attempt + 1))
    return None


def save(data):
    tmp = DATA_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    tmp.replace(DATA_PATH)


def main():
    data = json.load(open(DATA_PATH, encoding="utf-8"))
    todo = [e for e in data if not e.get("inline_url")]
    print(f"{len(data)} entries total, {len(todo)} still need inline_url", flush=True)

    done = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(fetch_inline_url, e["note_url"]): e for e in todo}
        for fut in as_completed(futures):
            e = futures[fut]
            url = fut.result()
            e["inline_url"] = url
            if url is None:
                failed += 1
            done += 1
            if done % 100 == 0:
                print(f"  ...{done}/{len(todo)} ({failed} failed so far)", flush=True)
                save(data)

    save(data)
    print(f"\nDone. {done} fetched, {failed} failed.", flush=True)


if __name__ == "__main__":
    main()
