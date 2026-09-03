"""Scrape Holy Grail library metadata into data/raw.json.

Does not download any PDFs - only scrapes the listing pages (name, subject,
year, doc type, uploader, note id, download url).

Usage:
    python scrape.py
    python scrape.py --category "GCE 'O' Levels" --subject "E Math" --subject "A Math"
    python scrape.py --doc-type "Exam Papers" --year 2023 --out data/econs_2023.json
"""
import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE = "https://grail.moe/library"
DEFAULT_CATEGORY = "GCE 'A' Levels"
DEFAULT_SUBJECTS = [
    "H2 Mathematics",
    "H2 Computing",
    "H2 Physics",
    "H2 Economics",
    "H2 Chemistry",
    "H1 General Paper",
]
DEFAULT_OUT_PATH = Path(__file__).parent / "data" / "raw.json"

HEADERS = {"User-Agent": "Mozilla/5.0 (grail-local-index-scraper)"}


def parse_page(html: str) -> list[dict]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for link in soup.find_all("a", href=lambda h: h and h.startswith("/library/")):
        card = link.parent.parent
        if card is None:
            continue
        fields = {}
        for row in card.select("div.grid > div"):
            label_el = row.find("p")
            value_el = label_el.find_next_sibling("p") if label_el else None
            if label_el and value_el:
                fields[label_el.get_text(strip=True)] = value_el.get_text(strip=True)

        dl = card.find("a", href=lambda h: h and "note/download/" in h)
        if not dl:
            continue
        note_id = dl["href"].rstrip("/").rsplit("/", 1)[-1]

        entries.append(
            {
                "id": note_id,
                "name": link.get_text(strip=True),
                "note_url": "https://grail.moe" + link["href"],
                "download_url": dl["href"],
                "category": fields.get("Category"),
                "subject": fields.get("Subject"),
                "doc_type": fields.get("Type"),
                "year": fields.get("Year"),
                "uploaded_by": fields.get("Uploaded By"),
                "uploaded_on": fields.get("Uploaded On"),
            }
        )
    return entries


def page_count(html: str) -> int:
    import re
    import sys

    m = re.search(r"Page<!-- -->1<!-- --> of <!-- -->(\d+)", html)
    if m:
        return int(m.group(1))

    # primary pattern didn't match - likely a Next.js markup change on grail.moe's side.
    # The looser fallback below still works for now, but warn loudly since a future
    # version bump could break it too and silently under-scrape (falling back to 1 page).
    m = re.search(r"of <!-- -->(\d+)", html)
    if m:
        print("WARNING: page_count() primary pattern didn't match, used the looser fallback - "
              "grail.moe's markup may have changed, double-check scraped counts look right",
              file=sys.stderr)
        return int(m.group(1))

    print("WARNING: page_count() found no page-count pattern at all, defaulting to 1 page - "
          "this subject/filter combo may be badly under-scraped", file=sys.stderr)
    return 1


def get_with_retry(session: requests.Session, params: dict, retries: int = 4) -> requests.Response | None:
    for attempt in range(retries):
        try:
            r = session.get(BASE, params=params, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(0.8 * (attempt + 1))
    return None  # give up on this page, caller skips it


def save_progress(all_entries: dict[str, dict], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(list(all_entries.values()), f, indent=2, ensure_ascii=False)
    tmp.replace(out_path)


def fetch_page(base_params: dict, page: int) -> tuple[int, list[dict]]:
    session = requests.Session()
    params = {**base_params, "page": page}
    r = get_with_retry(session, params)
    if r is None:
        return page, []
    return page, parse_page(r.text)


def scrape_subject(subject: str, base_filters: dict, all_entries: dict[str, dict],
                    out_path: Path, workers: int = 10):
    session = requests.Session()
    base_params = {**base_filters, "subject": subject}
    params = {**base_params, "page": 1}
    r = get_with_retry(session, params)
    if r is None:
        print(f"  {subject}: FAILED to load page 1, skipping subject", flush=True)
        return
    total_pages = page_count(r.text)
    for e in parse_page(r.text):
        all_entries[e["id"]] = e
    print(f"  {subject}: {total_pages} pages", flush=True)

    if total_pages < 2:
        return

    done = 0
    failed_pages = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_page, base_params, p): p for p in range(2, total_pages + 1)}
        for fut in as_completed(futures):
            page, entries = fut.result()
            if not entries:
                failed_pages.append(page)
            for e in entries:
                all_entries[e["id"]] = e
            done += 1
            if done % 20 == 0:
                print(f"    ...{done}/{total_pages - 1} pages ({len(all_entries)} total so far)", flush=True)
                save_progress(all_entries, out_path)

    if failed_pages:
        print(f"    retrying {len(failed_pages)} failed pages serially...", flush=True)
        for page in failed_pages:
            _, entries = fetch_page(base_params, page)
            for e in entries:
                all_entries[e["id"]] = e

    save_progress(all_entries, out_path)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--category", default=DEFAULT_CATEGORY,
                    help=f"Category to scrape, e.g. \"GCE 'A' Levels\", \"GCE 'O' Levels\", \"IP\" (default: {DEFAULT_CATEGORY!r})")
    p.add_argument("--subject", action="append", dest="subjects",
                    help="Subject to scrape (repeatable). Defaults to the 5 built-in A-level subjects if omitted.")
    p.add_argument("--doc-type", default=None,
                    help="Restrict to one document type, e.g. 'Exam Papers', 'TYS Answers', 'Notes/Practices'")
    p.add_argument("--year", default=None, help="Restrict to one year, e.g. 2023")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH, help="Output JSON path")
    p.add_argument("--workers", type=int, default=10, help="Concurrent page-fetch workers per subject")
    return p.parse_args()


def main():
    args = parse_args()
    subjects = args.subjects or DEFAULT_SUBJECTS

    base_filters = {"category": args.category}
    if args.doc_type:
        base_filters["doc_type"] = args.doc_type
    if args.year:
        base_filters["year"] = args.year

    all_entries: dict[str, dict] = {}

    for subject in subjects:
        print(f"Scraping {subject}...", flush=True)
        scrape_subject(subject, base_filters, all_entries, args.out, workers=args.workers)
        save_progress(all_entries, args.out)

    print(f"\nDone. {len(all_entries)} unique documents saved to {args.out}", flush=True)


if __name__ == "__main__":
    main()
