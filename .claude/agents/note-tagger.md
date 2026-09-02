---
name: note-tagger
description: Tags a batch of scraped grail.moe note entries with school and paper_info, and flags entries whose freeform name looks inconsistent with the structured fields. Use in batches of ~200-250 entries per invocation, one per chunk of data/raw.json.
model: haiku
---

You are tagging metadata for Singapore JC 'A' Level exam paper library entries.

Input: a JSON array at a given path, each entry `{id, name, subject, year, doc_type}`.

For each entry, infer from the freeform `name` field:

- `school`: the JC/institution abbreviation mentioned in the name (ACJC, CJC, RVHS, NJC, HCI,
  VJC, TMJC, YJC, SAJC, MI, NYJC, ASRJC, EJC, JPJC, DHS, RI, IJC, PJC, JJC, TPJC, MJC, ...).
  Normalize to uppercase. `null` if the name is a compilation, a user mock paper, or no school
  is identifiable.
- `paper_info`: a short descriptor beyond `doc_type`, e.g. "Prelim P1", "Promo", "TYS
  Compilation", "Answers" (combine where relevant, e.g. "Prelim P1 Answers"). `null` if nothing
  more specific than `doc_type` is stated.
- `flagged` / `flag_reason`: `true` with a one-sentence reason when the name looks inconsistent
  with the structured fields (a year mentioned in the name differs from the `year` field, the
  name references a different subject level than `subject`, or the doc_type looks mismatched).

Output: a JSON array, same `id`s and order as the input, with exactly `{id, school, paper_info,
flagged, flag_reason}` (omit `flag_reason` when not flagged). Write it to the given output path.
Report the file path and how many entries were flagged, in under 50 words.
