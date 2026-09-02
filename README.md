<div align="center">

# grail-wrapper

A local, faster, organized index for the grail.moe 'A' Level exam paper library

![Python](https://img.shields.io/badge/Python-3.10-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black)
![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)
![Last Commit](https://img.shields.io/github/last-commit/horse-3903/grail-wrapper?style=flat-square)

</div>

---

## Overview

**grail-wrapper** is a local wrapper around the [grail.moe](https://grail.moe/library) exam
paper library, presented as a UI titled **Holy Grail Mk 6 Index**. Instead of clicking through
hundreds of paginated listing pages, it scrapes the library's metadata once, enriches it with
Claude subagents and the Gemini API (school, paper info, review flags, answer-booklet links),
and serves a fast local search UI where every title opens the PDF directly. The core question
it answers: can a messy, freeform-named crowd-uploaded document library be turned into a clean,
browsable, correctly-grouped index without manually touching every one of its thousands of
entries.

## Features

- **Fast local search** - filter by subject, school, year range, document type, and paper number
  over the full scraped index, no page-by-page browsing on the live site
- **Multi-select filters** - School, Document type, and Paper accept multiple selected values at
  once via checkbox dropdowns; Year is a from/to range filter (a single year collapses the range
  to just that year)
- **Direct PDF links** - every title links straight to grail.moe's stable static PDF URL, opening
  inline in a new tab instead of forcing a download, with no bulk upfront download
- **Automatic tagging** - Claude Haiku subagents or the free Gemini API extract school and paper
  info from freeform filenames and flag entries whose name looks inconsistent with the site's
  structured fields, for a human (or another agent pass) to resolve
- **Exam-set grouping** - question papers and their answer booklets are grouped into one
  expandable row per exam sitting (badged "Exam Paper"), with question papers always listed
  before their answers, instead of scattered disconnected entries
- **Per-subject paper labels** - Paper 1/2/3/4 are labeled with what they actually are for each
  subject (e.g. H2 Economics P1 = Case Study Questions, H2 Computing P2 = Practical)
- **Configurable scraping** - target any category, subject, document type, or year via CLI flags,
  not hardcoded to the default subjects

## Tech Stack

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup4-4B8BBE?style=for-the-badge&logo=python&logoColor=white)
![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)
![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white)
![CSS3](https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white)

---

## Getting Started

### Prerequisites

- Python 3.10+
- `pip install flask requests beautifulsoup4 python-dotenv`

### Installation

```bash
git clone https://github.com/horse-3903/grail-wrapper.git
cd grail-wrapper
pip install flask requests beautifulsoup4 python-dotenv
```

### Run locally

```bash
python server.py
```

Then open http://127.0.0.1:8765

On Windows, `start_server.bat` starts the server and opens the browser automatically; it can be
targeted by a desktop shortcut.

### Re-scraping the index

`scrape.py` accepts flags to target any category, subject, document type, or year instead of the
default A-level subjects:

```bash
python scrape.py
python scrape.py --category "GCE 'O' Levels" --subject "E Math" --subject "A Math"
python scrape.py --doc-type "Exam Papers" --year 2023 --out data/econs_2023.json
```

After a fresh scrape, `fetch_inline_urls.py` fills in each entry's stable `document.grail.moe`
PDF link (fetching every note's detail page, since that link isn't on the listing pages):

```bash
python fetch_inline_urls.py
```

It's safe to re-run; it only fetches entries missing `inline_url`. School/paper-info tagging can
run unattended too, via the free Gemini API instead of a manual Claude Code subagent session
(get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey), put it in a
local `.env` as `GEMINI_API_KEY=...`):

```bash
python tag_with_gemini.py                 # tags entries in data/tagged.json missing school/paper_info
python tag_with_gemini.py --force          # re-tags everything (e.g. after a prompt change)
python tag_with_gemini.py --include-flagged # also re-tags entries currently flagged for review
```

Once tags are in place, `enrich.py` deterministically recomputes every derived field - resolved
year, standardized `display_name`, paper number/label, and exam-set `group_id` - from the raw
school/paper_info/year fields. Safe to re-run any time those inputs change; it leaves
subagent-linked groups (`linked|...`/`manual|...` ids) untouched:

```bash
python enrich.py
```

All three scripts back up the file they're about to overwrite to `data/backups/` first (skip
with `--no-backup`). Answer-booklet linking for the remaining unlinked "orphan" entries is still
a manual Claude Code session using the `answer-linker` subagent defined in `.claude/agents/`; see
[AGENTS.md](AGENTS.md) for the full pipeline and what each stage does.

---

## Deploying the static build

`web/` is a self-contained static copy of the UI (no server, no download proxy - every title
links straight to `inline_url`/`download_url`) for free hosting on Vercel, Netlify, or GitHub
Pages. On Vercel: import the repo, set **Root Directory** to `web`, framework preset **Other**,
deploy - no `vercel.json` needed.

To refresh the deployed data after re-scraping or re-tagging:

```bash
cp data/tagged.json web/data.json
```

then commit and push (or redeploy) `web/`. `static/index.html` and `web/index.html` are kept in
sync by hand whenever the UI changes - the only difference between them is how they load data
(`/api/notes` vs `./data.json`) and how titles link to PDFs.

---

## Project Structure

```
grail-wrapper/
├── scrape.py                # metadata scraper -> data/raw.json, CLI-configurable
├── fetch_inline_urls.py     # fills in each note's stable document.grail.moe PDF URL
├── tag_with_gemini.py       # unattended Gemini-based school/paper_info tagging
├── enrich.py                 # deterministic year/naming/paper-number/grouping pass
├── server.py                 # Flask app: serves the UI and the index over /api/notes
├── start_server.bat           # Windows launcher: starts the server and opens the browser
├── static/
│   └── index.html              # local-server UI (single-page, no build step)
├── web/
│   ├── index.html                # static build for free hosting (Vercel/Netlify/GitHub Pages)
│   └── data.json                  # snapshot of data/tagged.json bundled for the static build
├── data/
│   ├── raw.json                  # scraped metadata, no enrichment
│   ├── tagged.json                # raw.json + tags/year_resolved/display_name/group_id/inline_url
│   ├── manual_groups.json          # manual group overrides applied by server.py (usually empty)
│   └── backups/                     # timestamped pre-overwrite snapshots (gitignored)
├── .claude/agents/
│   ├── note-tagger.md              # subagent: tags school/paper_info, flags inconsistencies
│   └── answer-linker.md            # subagent: fuzzy-links question papers to answer booklets
├── AGENTS.md                # full pipeline reference for coding agents working on this repo
├── LICENSE
└── README.md
```

---

## `data/tagged.json` fields

Beyond the raw scraped fields (`name`, `category`, `subject`, `doc_type`, `note_url`,
`download_url`, `uploaded_by`, `uploaded_on`), each entry has:

- `inline_url` - the stable `document.grail.moe` URL for the file (a CloudFront link with no
  `Content-Disposition: attachment` header, so it opens inline instead of forcing a download);
  every title in the UI links here, falling back to `download_url` for the rare entry without one
- `school` - JC abbreviation extracted from the name, or `null`
- `paper_info` / `paper_info_base` / `paper_info_role` - e.g. "Prelim P1 Answers" splits into
  base "Prelim P1" (used for grouping) and role "Answers" (used for the badge in a group)
- `paper_number` / `paper_label` - the paper number (1-4) and its subject-specific meaning, e.g.
  H2 Economics Paper 1 = "Case Study Questions"
- `year_resolved` / `year_source` - the resolved year and whether it came from `"name"` or the
  original `"field"` (grail.moe's `year` field tracks upload date, not exam year)
- `display_name` / `original_name` - the standardized name and the original scraped name
- `group_id` - documents sharing a `group_id` render as one expandable exam-paper set in the UI
- `flagged` / `flag_reason` - set when the name still looks inconsistent after year resolution
  and needs a human look

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | none | Only needed for `tag_with_gemini.py`. Free key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey); put it in a local `.env` file (gitignored) or export it directly. |

The server port (`8765`) is set directly in `server.py`; no other environment variables are used.
