import copy

import pytest

from enrich import base_of, compute_group_id, enrich, find_paper_number, role_of

# --- base_of ---------------------------------------------------------------


@pytest.mark.parametrize("paper_info,expected", [
    ("Prelim P1 Answers", "Prelim P1"),
    ("Prelim P1", "Prelim P1"),
    ("QP", ""),
    ("Mark Scheme", ""),
    ("Prelim P1 Solutions", "Prelim P1"),
    ("", ""),
    (None, ""),
])
def test_base_of(paper_info, expected):
    assert base_of(paper_info) == expected


# --- role_of -----------------------------------------------------------


@pytest.mark.parametrize("paper_info,base,expected", [
    ("Prelim P1 Answers", "Prelim P1", "Answers"),
    ("Prelim P1", "Prelim P1", "Questions"),  # nothing left over after stripping base -> implicit Questions
    ("QP", "", "QP"),  # no base to strip against - role is the raw paper_info, unchanged
    ("", "", ""),
    (None, "", ""),
])
def test_role_of(paper_info, base, expected):
    assert role_of(paper_info, base) == expected


# --- find_paper_number -------------------------------------------------


def test_find_paper_number_from_base():
    assert find_paper_number("P1", "ACJC P1 QP", "H2 Mathematics", "P1 QP") == 1


def test_find_paper_number_from_original_name_when_base_has_no_number():
    assert find_paper_number("Prelim", "ACJC Prelim P2 QP", "H2 Mathematics", "Prelim") == 2


@pytest.mark.parametrize("paper_info_full,expected", [
    ("Prelim CSQ", 1),
    ("Case Study Q1", 1),
    ("Prelim Essay", 2),
])
def test_find_paper_number_econs_keyword_hints(paper_info_full, expected):
    assert find_paper_number("Prelim", "ACJC Prelim", "H2 Economics", paper_info_full) == expected


def test_find_paper_number_physics_practical_hint():
    assert find_paper_number("Practical", "school practical", "H2 Physics", "Practical") == 4


def test_find_paper_number_none_when_no_signal():
    assert find_paper_number("", "a completely generic name", "H2 Mathematics", "") is None


# --- compute_group_id ----------------------------------------------------


def _entry(**overrides):
    base = {"id": "1", "doc_type": "Exam Papers", "school": "ACJC",
            "year_resolved": "2020", "subject": "H2 Mathematics"}
    base.update(overrides)
    return base


def test_compute_group_id_groups_by_school_year_subject_topic():
    e = _entry()
    assert compute_group_id(e, "Prelim P1", 1) == "ACJC|2020|H2 Mathematics|Prelim"


def test_compute_group_id_same_topic_different_papers_share_group():
    e = _entry()
    gid_p1 = compute_group_id(e, "Prelim P1", 1)
    gid_p2 = compute_group_id(e, "Prelim P2", 2)
    assert gid_p1 == gid_p2  # P1 and P2 of the same sitting belong in one exam-set group


def test_compute_group_id_no_school_keeps_paper_number_split():
    e = _entry(school=None)
    # unknown-school uploads aren't provably the same source, so different paper
    # numbers stay split instead of being silently merged
    assert compute_group_id(e, "Prelim P1", 1) != compute_group_id(e, "Prelim P2", 2)


def test_compute_group_id_missing_year_uses_placeholder():
    e = _entry(year_resolved=None)
    assert compute_group_id(e, "Prelim P1", 1) == "ACJC|-|H2 Mathematics|Prelim"


def test_compute_group_id_non_groupable_doctype_is_always_singleton():
    e = _entry(doc_type="Notes/Practices")
    assert compute_group_id(e, "Prelim P1", 1) == "single|1"


def test_compute_group_id_empty_topic_is_singleton():
    # base_of("P1") == "" after NUM_RE strips the paper number, leaving nothing to group by
    e = _entry()
    assert compute_group_id(e, "P1", 1) == "single|1"


# --- enrich(): year resolution -----------------------------------------


def _raw_entry(**overrides):
    base = {
        "id": "1", "name": "ACJC P1 QP", "original_name": "ACJC P1 QP",
        "doc_type": "Exam Papers", "school": "ACJC", "subject": "H2 Mathematics",
        "year": "-", "paper_info": "P1", "flagged": False, "flag_reason": None,
        "group_id": "single|1",
    }
    base.update(overrides)
    return base


def test_enrich_prefers_year_in_name_over_field():
    data = [_raw_entry(name="ACJC 2020 P1 QP", year="2019")]
    out = enrich(copy.deepcopy(data))
    assert out[0]["year_resolved"] == "2020"
    assert out[0]["year_source"] == "name"


def test_enrich_falls_back_to_year_field_when_name_has_no_year():
    data = [_raw_entry(name="ACJC P1 QP", year="2019")]
    out = enrich(copy.deepcopy(data))
    assert out[0]["year_resolved"] == "2019"
    assert out[0]["year_source"] == "field"


@pytest.mark.parametrize("placeholder", ["-", "—"])
def test_enrich_treats_hyphen_and_em_dash_as_no_year(placeholder):
    # regression test: grail.moe's "no year" placeholder is sometimes an em dash rather than a
    # hyphen - year_resolved must stay None for either, not become the literal placeholder string
    data = [_raw_entry(name="ACJC P1 QP", year=placeholder)]
    out = enrich(copy.deepcopy(data))
    assert out[0]["year_resolved"] is None
    assert out[0]["year_source"] is None


def test_enrich_auto_clears_flag_once_year_resolves():
    data = [_raw_entry(name="ACJC 2020 P1 QP", flagged=True, flag_reason="no year found in the name")]
    out = enrich(copy.deepcopy(data))
    assert out[0]["flagged"] is False
    assert out[0]["flag_reason"] is None


def test_enrich_leaves_flag_alone_when_reason_is_unrelated_to_year():
    data = [_raw_entry(name="ACJC 2020 P1 QP", flagged=True, flag_reason="school could not be identified")]
    out = enrich(copy.deepcopy(data))
    assert out[0]["flagged"] is True


def test_enrich_backfills_school_from_name_when_missing():
    data = [_raw_entry(name="ACJC 2020 H2 Math P1 QP", school=None)]
    out = enrich(copy.deepcopy(data))
    assert out[0]["school"] == "ACJC"


def test_enrich_detects_answer_keyword_missed_by_tagger():
    name = "ACJC 2020 P1 Suggested Answers"
    data = [_raw_entry(name=name, original_name=name, paper_info="P1")]
    out = enrich(copy.deepcopy(data))
    assert "Answers" in out[0]["paper_info"]


def test_enrich_leaves_linked_and_manual_group_ids_untouched():
    data = [_raw_entry(group_id="linked|1|2"), _raw_entry(id="2", group_id="manual|foo")]
    out = enrich(copy.deepcopy(data))
    assert out[0]["group_id"] == "linked|1|2"
    assert out[1]["group_id"] == "manual|foo"


def test_enrich_is_idempotent():
    data = [_raw_entry(name="ACJC 2020 P1 QP")]
    once = enrich(copy.deepcopy(data))
    twice = enrich(copy.deepcopy(once))
    assert once == twice
