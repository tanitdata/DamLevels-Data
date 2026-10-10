"""Number parsing and cell semantic states.

Hard rule from the workspace contract, restated here because it is the single
easiest thing to get wrong: **a blank, a dash, an unknown cell, a spreadsheet
error and a hydraulic text state are never zero.** Each gets its own
``semantic_state`` and a null ``parsed_value``.

The bulletins print French-format numbers: comma decimal separator, space (or
narrow no-break space) thousands grouping, leading minus. PyMuPDF returns the
thousands group as a *separate word*, so ``1 896,282`` arrives as ``["1",
"896,282"]`` and must be joined left to right (see :mod:`text_and_encoding`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# --- semantic states ---------------------------------------------------- #
#: The accepted Phase 2 contracts already name this state ``numeric``. Using the
#: same word everywhere keeps one vocabulary across evidence and publication
#: tables; introducing a synonym would leave a consumer unable to rely on either.
STATE_NUMBER = "numeric"
STATE_BLANK = "blank"
STATE_DASH = "dash"
STATE_UPSTREAM_ERROR = "upstream_error"
STATE_HYDRAULIC_TEXT = "hydraulic_text_state"
STATE_TEXT = "text"
STATE_ROW_ABSENT = "row_absent"
STATE_SUSPECTED_TEXT_STATE = "suspected_text_state"
STATE_UNPARSEABLE = "unparseable_numeric_candidate"

SEMANTIC_STATES = (
    STATE_NUMBER,
    STATE_BLANK,
    STATE_DASH,
    STATE_UPSTREAM_ERROR,
    STATE_HYDRAULIC_TEXT,
    STATE_TEXT,
    STATE_ROW_ABSENT,
    STATE_SUSPECTED_TEXT_STATE,
    STATE_UNPARSEABLE,
)

#: States that carry a real number. Everything else has ``parsed_value = None``.
NUMERIC_STATES = (STATE_NUMBER,)

SPREADSHEET_ERROR_LITERALS = (
    "#N/A", "#VALUE!", "#REF!", "#DIV/0!", "#NAME?", "#NULL!", "#NUM!",
)

DASH_LITERALS = ("-", "--", "---", "–", "—", "_", "/")

#: Confirmed hydraulic text state (CLM-020): "flow over the spillway".
HYDRAULIC_TEXT_TERMS = (
    "انسياب عبر المفيض",
    "انسياب على المفيض",
    "انسياب",
    "المفيض",
)

_SPACE_CLASS = "     ⁠"
_TRANS_SPACES = {ord(c): " " for c in _SPACE_CLASS}

# One French-format number, optionally signed, optionally space-grouped.
_NUMBER_RE = re.compile(
    r"^[+-]?\d{1,3}(?:[ ]\d{3})*(?:,\d+)?$|^[+-]?\d+(?:,\d+)?$"
)
_HAS_DIGIT = re.compile(r"\d")
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")


@dataclass(frozen=True)
class ParsedCell:
    """Outcome of parsing one cell's text in a numeric position."""

    raw_text: str
    normalized_text: str
    parsed_value: Optional[float]
    semantic_state: str
    parse_method: str
    parse_note: str = ""

    @property
    def is_number(self) -> bool:
        return self.semantic_state == STATE_NUMBER

    def as_dict(self) -> dict[str, object]:
        return {
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "parsed_value": self.parsed_value,
            "semantic_state": self.semantic_state,
            "parse_method": self.parse_method,
            "parse_note": self.parse_note,
        }


def normalize_number_text(text: str) -> str:
    """Fold exotic spaces and Arabic-Indic digits; keep everything else intact."""
    s = unicodedata.normalize("NFKC", text).translate(_TRANS_SPACES)
    out = []
    for ch in s:
        if "٠" <= ch <= "٩":          # Arabic-Indic
            out.append(chr(ord(ch) - 0x0660 + 0x30))
        elif "۰" <= ch <= "۹":        # Extended Arabic-Indic
            out.append(chr(ord(ch) - 0x06F0 + 0x30))
        elif ch in "−–—":        # minus / en dash / em dash
            out.append("-")
        else:
            out.append(ch)
    return re.sub(r"[ ]+", " ", "".join(out)).strip()


def parse_numeric_cell(raw_text: str, *, allow_text_states: bool = True) -> ParsedCell:
    """Parse the text of a cell that a schema says should hold a number.

    Never returns ``0.0`` for anything that was not printed as a number.
    """
    raw = raw_text or ""
    norm = normalize_number_text(raw)

    if norm == "":
        return ParsedCell(raw, norm, None, STATE_BLANK, "EMPTY_CELL")

    upper = norm.upper()
    for lit in SPREADSHEET_ERROR_LITERALS:
        if lit in upper:
            return ParsedCell(raw, norm, None, STATE_UPSTREAM_ERROR, "SPREADSHEET_ERROR_LITERAL", lit)

    if norm in DASH_LITERALS:
        return ParsedCell(raw, norm, None, STATE_DASH, "DASH_LITERAL")

    if _NUMBER_RE.match(norm):
        return ParsedCell(raw, norm, _to_float(norm), STATE_NUMBER, "FRENCH_DECIMAL_STRICT")

    # Thousands groups that arrived as separate words: "1 896,282".
    joined = norm.replace(" ", "")
    if _NUMBER_RE.match(joined) and _looks_like_grouped(norm):
        return ParsedCell(
            raw, joined, _to_float(joined), STATE_NUMBER, "FRENCH_DECIMAL_SPACE_GROUPED"
        )

    if allow_text_states:
        for term in HYDRAULIC_TEXT_TERMS:
            if term in norm:
                return ParsedCell(raw, norm, None, STATE_HYDRAULIC_TEXT, "HYDRAULIC_VOCABULARY", term)

    if _ARABIC_LETTER.search(norm) and not _HAS_DIGIT.search(norm):
        return ParsedCell(raw, norm, None, STATE_TEXT, "ARABIC_TEXT_IN_NUMERIC_POSITION")

    if not _HAS_DIGIT.search(norm):
        # Control-substitution soup in a numeric position is the documented
        # detector for a text state the R1 text layer cannot show (CLM-020).
        return ParsedCell(
            raw, norm, None, STATE_SUSPECTED_TEXT_STATE, "NON_NUMERIC_NON_ARABIC_TOKEN"
        )

    return ParsedCell(raw, norm, None, STATE_UNPARSEABLE, "NO_RULE_MATCHED")


def _looks_like_grouped(norm: str) -> bool:
    """True when spaces separate a valid French thousands grouping.

    ``"1 896,282"`` yes; ``"12,3 45,6"`` no (two independent numbers).
    """
    parts = norm.split(" ")
    if len(parts) < 2:
        return False
    head = parts[0].lstrip("+-")
    if not head.isdigit() or not 1 <= len(head) <= 3:
        return False
    for p in parts[1:-1]:
        if not (p.isdigit() and len(p) == 3):
            return False
    tail = parts[-1]
    intpart, _, frac = tail.partition(",")
    if not (intpart.isdigit() and len(intpart) == 3):
        return False
    return frac == "" or frac.isdigit()


def _to_float(norm: str) -> float:
    return float(norm.replace(" ", "").replace(",", "."))


def parse_label_cell(raw_text: str) -> ParsedCell:
    """Classify a cell that a schema says should hold a label."""
    raw = raw_text or ""
    norm = normalize_number_text(raw)
    if norm == "":
        return ParsedCell(raw, norm, None, STATE_BLANK, "EMPTY_CELL")
    return ParsedCell(raw, norm, None, STATE_TEXT, "LABEL_CELL")


def dedupe_overprint(tokens: list[tuple[float, float, str]], *, tol: float = 0.15
                     ) -> tuple[list[tuple[float, float, str]], int]:
    """Drop tokens that repeat the same string at the same position.

    Overprinted rows (the same content drawn twice) are real in this corpus and
    were anticipated by FC-12. Deduplication is positional and exact-text-only,
    so two genuinely different values can never collapse into one. Returns the
    kept tokens and the number removed.
    """
    kept: list[tuple[float, float, str]] = []
    removed = 0
    for x0, y0, text in tokens:
        dup = any(
            t == text and abs(x0 - kx) <= tol and abs(y0 - ky) <= tol
            for kx, ky, t in kept
        )
        if dup:
            removed += 1
            continue
        kept.append((x0, y0, text))
    return kept, removed


def is_numeric_token(text: str) -> bool:
    n = normalize_number_text(text)
    return bool(_NUMBER_RE.match(n))


def format_value(value: Optional[float]) -> str:
    """Deterministic textual form for CSV output (never locale dependent)."""
    if value is None:
        return ""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(round(value, 6))
