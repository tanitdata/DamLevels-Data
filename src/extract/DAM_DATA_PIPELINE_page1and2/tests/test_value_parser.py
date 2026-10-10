from dam_extraction.common.contracts import TokenEvidence
from dam_extraction.page1.value_parser import parse_numeric


def ev(text, ambiguous=False):
    return TokenEvidence([text] if text else [], [], [], text, "TEST", text, ambiguous)


def test_source_states_never_become_zero():
    for text in ("", "-", "#N/A", "#VALEUR!"):
        assert parse_numeric(ev(text)).parsed_numeric_value is None


def test_attached_and_separated_footnotes():
    assert parse_numeric(ev("1,34*")).parsed_numeric_value == 1.34
    assert parse_numeric(ev("1,31 *")).parsed_numeric_value == 1.31


def test_ambiguous_not_guessed():
    parsed = parse_numeric(ev("00,,336611", ambiguous=True))
    assert parsed.parsed_numeric_value is None
    assert parsed.parser_state.value == "AMBIGUOUS_TOKEN"

