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
paper library. Instead of clicking through hundreds of paginated listing pages, it scrapes the
library's metadata once, enriches it with Claude subagents (school, paper info, review flags,
answer-booklet links), and serves a fast local search UI that downloads and caches PDFs on
demand. The core question it answers: can a messy, freeform-named crowd-uploaded document
library be turned into a clean, browsable, correctly-grouped index without manually touching
every one of its thousands of entries.

## Features

- **Fast local search** - filter by subject, school, year, document type, and paper number over
  the full scraped index, no page-by-page browsing on the live site
- **On-demand PDF caching** - PDFs download and cache locally only when you open them, not in a
  bulk upfront download
- **Automatic tagging** - Claude Haiku subagents extract school and paper info from freeform
  filenames and flag entries whose name looks inconsistent with the site's structured fields
- **Exam-set grouping** - question papers and their answer booklets are grouped into one
  expandable row per exam sitting, instead of scattered disconnected entries
- **Per-subject paper labels** - Paper 1/2/3/4 are labeled with what they actually are for each
  subject (e.g. H2 Economics P1 = Case Study Questions, H2 Computing P2 = Practical)
- **Configurable scraping** - target any category, subject, document type, or year via CLI flags,
  not hardcoded to the 5 default A-level subjects

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
- `pip install flask requests beautifulsoup4`

### Installation

```bash
git clone https://github.com/horse-3903/grail-wrapper.git
cd grail-wrapper
pip install flask requests beautifulsoup4
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
5 built-in A-level subjects:

```bash
python scrape.py
python scrape.py --category "GCE 'O' Levels" --subject "E Math" --subject "A Math"
python scrape.py --doc-type "Exam Papers" --year 2023 --out data/econs_2023.json
```

Re-running the tagging/grouping/linking enrichment pass (school and paper-info tagging, year
resolution, naming, exam-set grouping, answer-booklet linking) after a fresh scrape is a manual
Claude Code session using the subagents defined in `.claude/agents/`, not a single script.

---

## Project Structure

```
grail-wrapper/
├── scrape.py             # metadata scraper -> data/raw.json, CLI-configurable
├── server.py              # Flask app: serves the UI, proxies/caches PDF downloads
├── start_server.bat        # Windows launcher: starts the server and opens the browser
├── static/
│   └── index.html          # search/filter/grouping UI (single-page, no build step)
├── data/
│   ├── raw.json             # scraped metadata, no enrichment
│   └── tagged.json          # raw.json + school/paper_info/year_resolved/display_name/group_id
├── downloads/               # cached PDFs, populated on demand (gitignored)
├── .claude/agents/
│   ├── note-tagger.md        # subagent: tags school/paper_info, flags inconsistencies
│   └── answer-linker.md      # subagent: fuzzy-links question papers to answer booklets
├── LICENSE
└── README.md
```

---

## `data/tagged.json` fields

Beyond the raw scraped fields (`name`, `category`, `subject`, `doc_type`, `note_url`,
`download_url`, `uploaded_by`, `uploaded_on`), each entry has:

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
| - | - | None required. The server port (`8765`) is set directly in `server.py`. |
