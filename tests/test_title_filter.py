import pytest

from app.title_filter import TitleFilter


def test_forager_query_quotes_every_term_and_joins_with_or():
    title_filter = TitleFilter(include=["VP", "Head of Sales"], exclude=["Intern"])

    assert title_filter.forager_query() == '"VP" OR "Head of Sales"'


def test_forager_query_is_none_without_include_terms():
    assert TitleFilter(include=[], exclude=["Intern"]).forager_query() is None


def test_forager_query_strips_quotes_inside_terms():
    assert TitleFilter(include=['Chief "AI" Officer']).forager_query() == '"Chief AI Officer"'


@pytest.mark.parametrize(
    "title, expected",
    [
        ("VP of Engineering", True),
        ("vp, sales", True),
        ("Head of Sales EMEA", True),
        ("Senior Software Engineer", False),
        ("Director of Product", False),
        ("MVP Program Lead", False),  # word boundary: "VP" must not match inside "MVP"
        (None, False),
        ("", False),
    ],
)
def test_include_matching_is_case_insensitive_and_word_bounded(title, expected):
    assert TitleFilter(include=["VP", "Head of Sales"]).matches(title) is expected


def test_exclude_wins_over_include():
    title_filter = TitleFilter(include=["VP"], exclude=["Assistant"])

    assert title_filter.matches("Assistant to the VP") is False
    assert title_filter.matches("VP Marketing") is True


def test_empty_include_allows_everything_not_excluded():
    title_filter = TitleFilter(include=[], exclude=["Intern"])

    assert title_filter.matches("Software Engineer") is True
    assert title_filter.matches("Research Intern") is False


def test_cto_does_not_match_director():
    assert TitleFilter(include=["CTO"]).matches("Director") is False


def test_blank_terms_are_ignored():
    title_filter = TitleFilter(include=[" ", "CEO"], exclude=[""])

    assert title_filter.include == ["CEO"]
    assert title_filter.exclude == []


def test_describe_is_human_readable():
    assert TitleFilter(include=["CEO", "VP"], exclude=["Intern"]).describe() == "include: CEO, VP; exclude: Intern"
