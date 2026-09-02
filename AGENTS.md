# AGENTS.md

Reference for coding agents (and future-me) working on this repo. Read this before touching
`data/tagged.json`, the enrichment pipeline, or either `index.html`.

## What this project is

A local wrapper around [grail.moe](https://grail.moe/library), a crowd-uploaded Singapore JC
'A' Level exam paper library. grail.moe's own site is slow to browse (paginated listings, no
grouping of a question paper with its answer key, downloads instead of opening PDFs inline). This
project scrapes the metadata once, runs it through an enrichment pipeline, and serves it from a
fast local single-page UI titled **Holy Grail Mk 6 Index**.

Originally scoped to 5 subjects (H2 Mathematics, H2 Computing, H2 Physics, H2 Economics, H1
General Paper) - that scope lives in `scrape.py`'s `DEFAULT_SUBJECTS`, overridable per-run via
`--subject`. `data/tagged.json` currently also contains a 6th subject, **H1 Economics**: entries
that were scraped under the H2 Economics grail.moe category but whose filenames turned out to
be H1 Economics content (caught by the tagger's flagging, then relabeled - see "Flags" below).

## Pipeline (run in this order)

```
scrape.py  ->  tag_with_gemini.py (or note-tagger subagent)  ->  enrich.py  ->  answer-linker subagent (optional)  ->  fetch_inline_urls.py
```

1. **`scrape.py`** - hits `grail.moe/library` listing pages (server-rendered Next.js, paginated
   10/page) with `category`/`subject`/`doc_type`/`year`/`page` query params, concurrently via
   `ThreadPoolExecutor`. Writes `data/raw.json`. Every entry gets `download_url`
   (`api.grail.moe/note/download/{id}`, a redirect to a short-lived presigned S3 URL with
   `Content-Disposition: attachment` - this forces a download, do not use it as the primary link).
2. **Tagging** - fills `school` and `paper_info` from the freeform `name` field, plus
   `flagged`/`flag_reason` for names that look inconsistent with the structured fields. Two
   interchangeable ways to do this:
   - `tag_with_gemini.py` - unattended, calls the Gemini API (`gemini-3.6-flash`; if you see a
     404 telling you a model was retired, that's the fix - bump `MODEL` to whatever the error
     message names). Needs `GEMINI_API_KEY` in `.env` (gitignored) or the environment.
   - The `note-tagger` Claude Code subagent (`.claude/agents/note-tagger.md`) - dispatch
     manually in batches of ~200-250 entries per invocation; only works inside an interactive
     Claude Code session, can't be scripted/automated the way the Gemini path can.
   Both write the same shape: `{id, school, paper_info, flagged, flag_reason}` merged back into
   the entries.
3. **`enrich.py`** - the deterministic pass. Recomputes, for every entry:
   - `year_resolved`/`year_source` - prefers a year parsed out of the *name* over grail.moe's
     `year` field, because that field tracks upload date, not exam year.
   - `school` - regex sweep over `original_name` for entries the tagger missed (catches
     underscore-joined filenames like `NJC_2019_Prelim`).
   - `paper_info_base`/`paper_info_role`, `paper_number`/`paper_label`, `display_name`.
   - `group_id` - documents sharing one exam sitting (papers + their answers) get the same
     `group_id` so the UI renders them as one expandable row. For a *known* school, all papers
     of one sitting merge into one group; for an *unknown* school, groups stay split by paper
     number, since two anonymous uploads can't be assumed to be the same sitting.
   Entries whose `group_id` already starts with `linked|` or `manual|` are left alone - those
   came from the answer-linker subagent or the (currently disabled) manual-grouping UI, and
   encode judgment this script can't reproduce.
4. **`answer-linker` subagent** (`.claude/agents/answer-linker.md`) - for the "orphan" entries
   `enrich.py`'s `paper_info`-based grouping couldn't confidently pair (fuzzy filename matching
   across a whole subject/year). Manual, interactive-session-only, same as `note-tagger`.
5. **`fetch_inline_urls.py`** - fetches every note's *detail* page (`note_url`) to extract the
   stable `document.grail.moe/<hash>.<ext>` CloudFront link via regex (widened to match any
   extension, not just `.pdf` - H2 Computing practicals ship as `.zip`). This link has no
   `Content-Disposition` header, so it opens inline instead of forcing a download. It's on the
   detail page only, not the listing pages scrape.py reads. Idempotent - only fetches entries
   missing `inline_url`.

All four scripts that touch `data/tagged.json` (`tag_with_gemini.py`, `enrich.py`,
`fetch_inline_urls.py`, and any ad-hoc script) should back up the file to `data/backups/`
(timestamped, gitignored) before overwriting - `tag_with_gemini.py` and `enrich.py` already do
this by default (`--no-backup` to skip). **Always back up before a bulk rewrite of tagged.json** -
this repo has already lost enrichment work once from skipping that.

After any pipeline run: `cp data/tagged.json web/data.json` to keep the static build's bundled
snapshot in sync.

## Flags (`flagged`/`flag_reason`)

Entries the tagger thinks look inconsistent with their structured fields. As of the last cleanup
pass, all flags were resolved this way (use as precedent for future flag review, not as a
standing rule to reapply blindly):

- **Year mismatch** where the year genuinely is in the name but a regex `\b` boundary failed on
  an adjacent underscore (`2007_AJC_..._solutions` - `\b` treats `_` as a word character, so
  there's no boundary between `7` and `_`). Fixed in `enrich.py`'s `YEAR_RE` by switching to
  `(?<![A-Za-z0-9])...(?![A-Za-z0-9])` lookaround (same pattern `NUM_RE` already used for paper
  numbers). If you add more `\b`-based regexes over `original_name`, expect the same bug.
- **doc_type mismatch** (grail.moe's own site category says "Exam Papers" but the name is
  clearly a tutorial/worksheet/notes set) - reclassified `doc_type` to `Notes/Practices` to match
  the actual content, since the site's per-upload categorization isn't authoritative.
- **Subject mismatch** (39 entries scraped under the H2 Economics grail.moe category, named
  `*_H1_ECON_*`) - relabeled `subject` to `"H1 Economics"` rather than deleting them or leaving
  the wrong subject in place. This is why H1 Economics now appears as a 6th subject in the UI
  even though it was never in `scrape.py`'s `DEFAULT_SUBJECTS`.

## UI: `static/index.html` and `web/index.html`

Two near-identical single-file HTML/CSS/JS apps, **not build-generated from a shared source** -
edit both by hand, in the same way, every time. The only intentional differences:

| | `static/index.html` | `web/index.html` |
|---|---|---|
| Served by | `server.py` (`GET /`) | any static host (Vercel/Netlify/GitHub Pages), `web/` as root |
| Data source | `fetch("/api/notes")` | `fetch("./data.json")` |
| PDF link helper | same `pdfUrl(e)` (`inline_url \|\| download_url`) | same |

When changing one, `grep` the other for the same selector/function name and apply the same edit.
There is no shared JS module - it's copy-paste by design (no build step, no bundler).

Key JS internals worth knowing before touching filtering/rendering:

- **`matchesFilters(e, f)` takes a precomputed filter-state object `f`**, not live DOM reads.
  This was a deliberate perf fix - with 3300+ documents, reading `getElementById(...).value` for
  every filter control inside a per-entry predicate redid that work thousands of times per
  keystroke. `getFilterState()` reads the DOM once per `applyFilters()` call; keep it that way.
- **School / Document type / Paper filters** are checkbox-dropdown multi-selects
  (`multiFilters.school/doctype/paper`, each a `Set`), not native `<select>`. Year is a min/max
  range (`yearMin`/`yearMax`) via two "From"/"To" text inputs, applied on an Apply button or
  Enter keypress; when `yearMin === yearMax` the trigger label collapses to the single year
  instead of showing `2023–2023`.
- **`.filter-group > label` uses a direct-child combinator, not a bare descendant selector.**
  It's a leftover-bug trap: the checkbox rows inside the multi-select dropdown panels
  (`.ms-option`) are also `<label>` elements, and a bare `.filter-group label` selector will
  silently reskin them with the field-caption font (mono, uppercase, small) instead of the body
  font. If you add another `<label>` anywhere under `.filter-group`, make sure it doesn't
  inherit that rule unintentionally.
- **Group `primary` must be recomputed from the *filtered* members, not the group's original
  members**, whenever you build the `visible` list in `applyFilters()`. Otherwise a group's
  header (title, paper-number-derived name) can describe a member that got filtered out - e.g.
  filtering to Paper 1 while a group's header still says "Paper 2" because the header was built
  from the unfiltered `primary`. Already fixed once; don't reintroduce it.
- **Rows are capped at 600** (`groups.slice(0, 600)` in `renderRows`) for render performance.
  Increase only if you also address DOM node count some other way.
- **The results scrollbar is intentionally hidden** (`scrollbar-width: none` +
  `::-webkit-scrollbar{display:none}` on `.results-scroll`) so rows sit flush with the
  `.col-headers` above them; the area still scrolls, just without a visible scrollbar.
- Design linting: `npx impeccable detect <file>` checks contrast, font-size, and layout
  anti-patterns. Run it after any CSS change. One known-and-verified-harmless finding,
  `clipped-overflow-container` (body's `overflow: hidden` technically wraps the absolutely
  positioned `.ms-panel` dropdowns), is a false positive here - the panels render fully within
  the viewport in practice since the filter bar sits near the top of the page. Don't "fix" it by
  loosening `body { overflow: hidden }`, which is load-bearing for the app's fixed-viewport
  layout (header + filter bar + internally-scrolling results).
- **Do not verify UI changes with a browser tool** - lint with impeccable and reason about the
  code instead. This is an explicit standing preference, not a one-off.

### Dark mode

Theming is CSS custom properties on `:root`, overridden under `:root[data-theme="dark"]`. Every
color used more than once (or that needs a dark counterpart) is a variable - if you hardcode a
new hex color anywhere in the row/badge/filter CSS, dark mode will look wrong for it. The
`#theme-toggle` button in the header flips `data-theme` on `<html>` and persists the choice to
`localStorage["grail-theme"]`; on first load (`initTheme()`), it falls back to
`prefers-color-scheme` if nothing is stored. Both `localStorage` calls are wrapped in `try/catch`
since some browser privacy modes throw on access.

## Editing metadata/grouping from the UI (local server only)

`static/index.html` has a per-row "Edit" button (next to "Source", on expanded group members and
on ungrouped rows - not on collapsed group headers, since a group can have multiple members and
editing "the group" would be ambiguous) that opens a modal covering two different things:

**Metadata** (School, Paper Info, Subject, Document Type, Year, Paper Number) - edited as plain
text fields, saved via the modal's Save button, which sends `PATCH /api/note/<id>`. That handler:

1. **Backs up `data/tagged.json` to `data/backups/`** before writing (same `backup_tagged()`
   pattern the CLI scripts use - every write path into this file backs up first, no exceptions).
2. Applies the edited fields directly, recomputes only the display-cosmetic derived fields
   (`display_name`, `paper_info_base`, `paper_info_role`, `paper_label`) via `enrich.py`'s
   `base_of()`/`role_of()`/`SUBJECT_PAPER_LABELS`/`SUBJ_ABBR` helpers - it does **not** re-run
   `enrich.py`'s year-resolution, school-sweep, or auto-grouping logic on the whole dataset, so
   editing one row can't have side effects on unrelated entries.

**Grouping** - not a raw `group_id` text field (too easy to typo, and typing an unprefixed
string that happens to collide with an existing computed key would silently and confusingly
regroup things). Instead:

- A live search box matches against every group's display name, school, subject, year, and
  member filenames; clicking a result immediately `POST`s `/api/note/<id>/merge` with that
  group's real `target_group_id`.
- `api_merge_note()` in `server.py` protects the merge from `enrich.py`'s next run by rewriting
  **every current member of the target group** (not just the newly added entry) onto a
  `manual|`-prefixed id, if it isn't already `manual|`/`linked|`. Prefixing only the new entry
  and leaving its groupmates unprefixed would desync them the moment `enrich.py` recomputes the
  groupmates' (still deterministic) ids - they'd stay put, the new entry would drift, and the
  merge would silently undo itself. Prefixing the whole group at once is what makes it stick.
- "Split into its own group" (shown only when the entry currently has groupmates) `POST`s
  `/api/note/<id>/ungroup`, which recomputes that one entry's *natural* group_id via
  `enrich.py`'s `compute_group_id()` - the same function `enrich()`'s main loop calls - so a
  split entry can still land next to its real school/year/subject peers on its own merits, just
  without whatever manual/linked override was pinning it elsewhere.
- Both endpoints return the full updated `entries` list (not just the one changed entry, since a
  merge can touch several), and the client replaces `DATA`/`GROUPS` wholesale from that response.

**This feature is `static/index.html` + `server.py` only.** `web/index.html` is a static build
with nowhere to persist a PATCH/POST, so it deliberately does not get the Edit button or modal -
only mirror the dark-mode CSS/JS changes there, not the editor.

## Environment quirks (this machine)

- `python3` on PATH resolves to a broken Windows Store shim that errors immediately. Use
  `python` (aliases to the real 3.10 install) for all one-off scripts and pipeline runs.
- Bash heredocs (`python3 << 'EOF' ... EOF`) have been unreliable in this environment (silent
  non-zero exits with no output) - write a `.py` file and run `python path/to/file.py` instead.
- `.env` (gitignored) holds `GEMINI_API_KEY`. Never commit it; `git check-ignore -v .env` should
  confirm it's ignored if you're ever unsure.

## Conventions specific to this repo

- Git author is Rafael Chong (`chongchoonhourafael@gmail.com`), pulled from global git config -
  don't override it.
- Commit messages: one concise line, no trailer, no `Co-Authored-By` (see the user's global
  `CLAUDE.md` for the full house style - it applies here like everywhere else).
- Never bulk-download PDFs. The whole point of `inline_url`/`download_url` is linking to
  grail.moe's own hosting on demand; this repo does not mirror file contents.
- Prefer editing `enrich.py`/`tag_with_gemini.py`/`fetch_inline_urls.py` over one-off inline
  Python for anything that might need to be re-run later - the throwaway-heredoc approach is how
  this repo previously lost enrichment work (overwrote `tagged.json` with an intermediate stage,
  no backup taken first).
