from scrape import page_count


def test_page_count_primary_pattern():
    html = "<span>Page<!-- -->1<!-- --> of <!-- -->42</span>"
    assert page_count(html) == 42


def test_page_count_fallback_pattern_warns(capsys):
    html = "<span>of <!-- -->7</span>"  # primary pattern absent, only the looser one matches
    assert page_count(html) == 7
    assert "WARNING" in capsys.readouterr().err


def test_page_count_defaults_to_one_and_warns_when_nothing_matches(capsys):
    html = "<span>no page info here</span>"
    assert page_count(html) == 1
    assert "WARNING" in capsys.readouterr().err
