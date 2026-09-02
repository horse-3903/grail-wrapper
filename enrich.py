"""Deterministic enrichment pass over data/tagged.json: year resolution, school-regex
sweep, standardized naming, paper-number/label extraction, and exam-set grouping.

Safe to re-run any time after scrape.py / tag_with_gemini.py / the note-tagger subagent
change school/paper_info/year - this recomputes every derived field from scratch, except
group_id for entries already merged by the answer-linker subagent ("linked|..." groups),
which are left untouched since that grouping came from fuzzy human-style judgment this
script can't reproduce.
"""
import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent / "data" / "tagged.json"

YEAR_RE = re.compile(r"(?<![A-Za-z0-9])(19[5-9]\d|20[0-4]\d)(?![A-Za-z0-9])")

KNOWN_SCHOOLS = ["ACJC", "ASRJC", "EJC", "TMJC", "NYJC", "RVHS", "JPJC", "YIJC", "HCI", "DHS",
                 "RI", "NJC", "VJC", "CJC", "TJC", "SAJC", "MI", "IJC", "MJC", "AJC", "SRJC",
                 "PJC", "YJC", "JJC", "XJC", "RJC", "TPJC"]
KNOWN_SCHOOLS.sort(key=len, reverse=True)
SCHOOL_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(KNOWN_SCHOOLS) + r")(?![A-Za-z])", re.IGNORECASE)

SUFFIX_RE = re.compile(
    r"\b(Answers?|Solutions?|Soln|Qn|Questions?|QP|Insert|Guide|Mark ?Scheme)\b", re.IGNORECASE
)
NUM_RE = re.compile(r"(?<![A-Za-z0-9])P(?:aper)?\.?\s*([1-4])(?![0-9])", re.IGNORECASE)

SUBJ_ABBR = {
    "H2 Mathematics": "H2 Math", "H2 Computing": "H2 Comp", "H2 Physics": "H2 Phy",
    "H2 Economics": "H2 Econs", "H1 General Paper": "GP",
}
SUBJECT_PAPER_LABELS = {
    "H2 Mathematics": {1: "Pure Mathematics", 2: "Mathematics & Statistics"},
    "H2 Computing": {1: "Theory", 2: "Practical"},
    "H2 Physics": {1: None, 2: None, 3: None, 4: "Practical"},
    "H2 Economics": {1: "Case Study Questions", 2: "Essays"},
    "H1 General Paper": {1: "Essay", 2: "Comprehension"},
}
KEYWORD_HINTS = {
    "H2 Economics": [(re.compile(r"case study|\bcsq\b", re.I), 1), (re.compile(r"\bessay", re.I), 2)],
    "H1 General Paper": [(re.compile(r"compre", re.I), 2), (re.compile(r"\bessay", re.I), 1)],
    "H2 Computing": [(re.compile(r"theory", re.I), 1), (re.compile(r"practical", re.I), 2)],
    "H2 Physics": [(re.compile(r"practical", re.I), 4)],
}
GROUPABLE_TYPES = {"Exam Papers", "TYS Answers", "MYEs/CAs/Other Tests"}

ANSWER_KEYWORD_RE = re.compile(
    r"\b(ans|answers?|sol|soln|solutions?|suggested\s+answers?|mark\s*scheme|marking\s*scheme|\bms\b)\b",
    re.IGNORECASE,
)
ALREADY_SIGNALS_RE = re.compile(r"answer|solution|\bms\b|mark\s*scheme", re.IGNORECASE)


def base_of(paper_info: str) -> str:
    if not paper_info:
        return ""
    return re.sub(r"\s+", " ", SUFFIX_RE.sub("", paper_info)).strip()


def role_of(paper_info: str, base: str) -> str:
    if not paper_info:
        return ""
    role = paper_info
    if base:
        role = role.replace(base, "").strip()
    return role or "Questions"


def find_paper_number(base: str, original_name: str, subject: str, paper_info_full: str):
    for source in (base, original_name):
        m = NUM_RE.search(source or "")
        if m:
            return int(m.group(1))
    for pattern, num in KEYWORD_HINTS.get(subject, []):
        if pattern.search(paper_info_full or "") or pattern.search(original_name or ""):
            return num
    return None


def enrich(data: list[dict]) -> list[dict]:
    # 1. detect answer/solution/mark-scheme keywords the tagger might have missed
    for e in data:
        if not ANSWER_KEYWORD_RE.search(e["original_name"]):
            continue
        current = e.get("paper_info") or ""
        if ALREADY_SIGNALS_RE.search(current):
            continue
        e["paper_info"] = (current + " Answers").strip()

    # 2. year resolution: prefer the year in the name over grail.moe's upload-date field
    for e in data:
        m = YEAR_RE.search(e["name"])
        name_year = m.group(0) if m else None
        field_year = e["year"] if e.get("year") and e["year"] != "-" else None
        if name_year:
            e["year_resolved"] = name_year
            e["year_source"] = "name"
        elif field_year:
            e["year_resolved"] = field_year
            e["year_source"] = "field"
        else:
            e["year_resolved"] = None
            e["year_source"] = None
        reason = (e.get("flag_reason") or "").lower()
        if e.get("flagged") and "year" in reason and e["year_resolved"]:
            e["flagged"] = False
            e["flag_reason"] = None

    # 3. school regex sweep for entries the tagger missed (handles underscore-joined names)
    for e in data:
        if not e.get("school"):
            m = SCHOOL_RE.search(e["original_name"] if "original_name" in e else e["name"])
            if m:
                e["school"] = m.group(1).upper()

    # 4. naming, paper number/label, canonical grouping
    for e in data:
        e.setdefault("original_name", e["name"])
        subj_abbr = SUBJ_ABBR.get(e["subject"], e["subject"] or "")
        base = base_of(e.get("paper_info"))
        e["paper_info_base"] = base
        e["paper_info_role"] = role_of(e.get("paper_info"), base)

        n = find_paper_number(base, e["original_name"], e["subject"], e.get("paper_info"))
        label = SUBJECT_PAPER_LABELS.get(e["subject"], {}).get(n) if n else None
        e["paper_number"] = n
        e["paper_label"] = label

        old_gid = e.get("group_id", "")
        if not old_gid.startswith("linked|") and not old_gid.startswith("manual|"):
            topic = re.sub(r"\s+", " ", NUM_RE.sub("", base)).strip()
            if e["doc_type"] in GROUPABLE_TYPES and topic:
                if e.get("school"):
                    key = topic
                else:
                    # unknown school: different anonymous uploads aren't provably the same
                    # source, so keep them split by paper number to avoid false merges
                    key = f"{topic} P{n}" if n else topic
                school_part = e.get("school") or "-"
                e["group_id"] = f"{school_part}|{e['year_resolved'] or '-'}|{e['subject']}|{key}"
            else:
                e["group_id"] = f"single|{e['id']}"

        school_prefix = f"{e['school']} " if e.get("school") else ""
        tail = e.get("paper_info") or e["doc_type"] or ""
        e["display_name"] = f"{school_prefix}{e['year_resolved'] or '-'} {subj_abbr} {tail}".strip()

    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="in_path", type=Path, default=DEFAULT_PATH)
    ap.add_argument("--out", dest="out_path", type=Path, default=None, help="defaults to --in (in place)")
    ap.add_argument("--no-backup", action="store_true", help="skip archiving out_path before overwriting it")
    args = ap.parse_args()
    out_path = args.out_path or args.in_path

    if out_path.exists() and not args.no_backup:
        backup_dir = Path("data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{out_path.stem}_{stamp}{out_path.suffix}"
        backup_path.write_bytes(out_path.read_bytes())
        print(f"Backed up {out_path} -> {backup_path}", flush=True)

    data = json.load(open(args.in_path, encoding="utf-8"))
    data = enrich(data)
    json.dump(data, out_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)

    groups = defaultdict(list)
    for e in data:
        groups[e["group_id"]].append(e)
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    n_school = sum(1 for e in data if e.get("school"))
    print(f"{len(data)} entries, {n_school} with school ({n_school/len(data):.0%}), "
          f"{len(groups)} groups ({len(multi)} multi-member)", flush=True)


if __name__ == "__main__":
    main()
