from __future__ import annotations

import re

from dam_extraction.common.contracts import ParsedValue, ParserState, TokenEvidence

DASHES = {"-", "–", "—"}
NOT_APPLICABLE = {"#N/A", "N/A", "NA"}
NONNUMERIC_EXPRESSIONS = {"#VALEUR!", "#VALUE!", "#DIV/0!", "#REF!"}


def parse_numeric(evidence: TokenEvidence) -> ParsedValue:
    if evidence.ambiguous:
        return ParsedValue(ParserState.AMBIGUOUS_TOKEN, None)
    raw = evidence.normalized_parse_input.strip()
    if not raw:
        return ParsedValue(ParserState.SOURCE_BLANK, None)
    if raw in DASHES or raw.upper() in NOT_APPLICABLE:
        return ParsedValue(ParserState.SOURCE_NOT_APPLICABLE, None)
    if raw.upper() in NONNUMERIC_EXPRESSIONS or raw.startswith("#"):
        return ParsedValue(ParserState.SOURCE_NONNUMERIC_EXPRESSION, None)
    footnote = None
    match = re.fullmatch(r"([-+]?\d[\d\s.'’]*?(?:[,.]\d+)?)\s*(\*+|\([A-Za-z0-9]+\))", raw)
    if match:
        raw, footnote = match.groups()
    compact = raw.replace("\u00a0", "").replace(" ", "").replace("'", "").replace("’", "")
    if re.fullmatch(r"[-+]?\d+(?:[,.]\d+)?", compact):
        value = float(compact.replace(",", "."))
        state = ParserState.SOURCE_NUMERIC_WITH_FOOTNOTE if footnote else ParserState.NUMERIC_PARSED
        return ParsedValue(state, value, footnote)
    return ParsedValue(ParserState.AMBIGUOUS_TOKEN, None)
