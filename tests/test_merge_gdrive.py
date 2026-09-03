from merge_gdrive import dedupe, find_gaps


def _entry(id_, group_id, paper_number, role_hint, name_len=20):
    return {
        "id": id_, "group_id": group_id, "paper_number": paper_number,
        "paper_info_role": role_hint, "school": group_id.split("|")[0],
        "year_resolved": group_id.split("|")[1] if "|" in group_id else None,
        "subject": "H2 Mathematics", "original_name": "x" * name_len,
    }


# --- find_gaps -----------------------------------------------------------


def test_find_gaps_skips_paper_already_covered_in_same_group():
    existing = [_entry("e1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions")]
    drive = [_entry("d1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions")]
    assert find_gaps(drive, existing) == []


def test_find_gaps_skips_paper_covered_under_a_different_group_id_same_school_year_subject():
    # topic word can differ slightly between sources even though it's the same sitting -
    # the school/year/subject/paper/role signature is what actually matters
    existing = [_entry("e1", "ACJC|2020|H2 Mathematics|Promo", 1, "Questions")]
    drive = [_entry("d1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions")]
    assert find_gaps(drive, existing) == []


def test_find_gaps_keeps_paper_not_covered_anywhere():
    existing = [_entry("e1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions")]
    drive = [_entry("d1", "ACJC|2020|H2 Mathematics|Prelim", 2, "Questions")]
    gaps = find_gaps(drive, existing)
    assert [g["id"] for g in gaps] == ["d1"]


def test_find_gaps_treats_questions_and_answers_as_distinct_signals():
    existing = [_entry("e1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions")]
    drive = [_entry("d1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Suggested Answers")]
    gaps = find_gaps(drive, existing)
    assert [g["id"] for g in gaps] == ["d1"]


# --- dedupe ----------------------------------------------------------------


def test_dedupe_collapses_same_paper_to_shortest_name():
    gaps = [
        _entry("d1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions", name_len=40),
        _entry("d2", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions", name_len=10),
    ]
    deduped = dedupe(gaps)
    assert len(deduped) == 1
    assert deduped[0]["id"] == "d2"


def test_dedupe_breaks_length_tie_by_id():
    gaps = [
        _entry("z1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions", name_len=10),
        _entry("a1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions", name_len=10),
    ]
    deduped = dedupe(gaps)
    assert len(deduped) == 1
    assert deduped[0]["id"] == "a1"


def test_dedupe_keeps_distinct_papers_separate():
    gaps = [
        _entry("d1", "ACJC|2020|H2 Mathematics|Prelim", 1, "Questions"),
        _entry("d2", "ACJC|2020|H2 Mathematics|Prelim", 2, "Questions"),
    ]
    deduped = dedupe(gaps)
    assert {e["id"] for e in deduped} == {"d1", "d2"}
