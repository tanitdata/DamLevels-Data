"""Arabic text, encoding regimes, and normalization.

Three measured regimes bind this module (KB-ANCHORS-REGIMES, CLM-018):

``R1_c0_control_substitution``
    Arabic glyphs replaced by C0 control bytes. Unrecoverable from the text
    layer. Anchors are confirmation-only; routing must be geometry-first.
``R2_presentation_forms``
    U+FB50-FEFF presentation forms. NFKC recovers the text completely.
``R3_standard_letters_lamalef_reversed``
    Valid letters, but lam-alef ligatures stored in reversed order
    (``ملاحظات`` -> ``مالحظات``). Exact string equality fails.

Two hazards recorded in the same source and honoured here:

* ``get_text("words")`` silently strips C0 controls, so a health metric read
  from the words layer lies on R1 files. Health is measured from the *text*
  layer.
* Tatweel (U+0640) runs split words; strip it before matching.

Nothing in this module repairs uncertain text. It produces a normalized form
*alongside* the raw form and records which method produced it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

R1 = "R1_c0_control_substitution"
R2 = "R2_presentation_forms"
R3 = "R3_standard_letters_lamalef_reversed"
R_HEALTHY_UNKNOWN = "R0_no_arabic_detected"

TEXT_REGIMES = (R1, R2, R3, R_HEALTHY_UNKNOWN)

TATWEEL = "ـ"
ARABIC_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭ]")
PRESENTATION_FORM_RANGE = (0xFB50, 0xFEFF)
ARABIC_RANGE = (0x0600, 0x06FF)

# Lam-alef pairs and the reversed two-character sequence R3 files store instead.
LAM = "ل"
ALEF_FORMS = ("ا", "أ", "إ", "آ")

REPLACEMENT_CHAR = "�"


@dataclass(frozen=True)
class TextHealth:
    """Per-page text-layer measurement. All counts come from the text layer."""

    text_chars: int
    arabic_chars: int
    presentation_form_chars: int
    control_chars: int
    replacement_chars: int
    digit_chars: int
    encoding_regime: str
    arabic_recoverable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "text_chars": self.text_chars,
            "arabic_chars": self.arabic_chars,
            "presentation_form_chars": self.presentation_form_chars,
            "control_chars": self.control_chars,
            "replacement_chars": self.replacement_chars,
            "digit_chars": self.digit_chars,
            "encoding_regime": self.encoding_regime,
            "arabic_recoverable": self.arabic_recoverable,
        }


def _is_arabic(ch: str) -> bool:
    return ARABIC_RANGE[0] <= ord(ch) <= ARABIC_RANGE[1]


def _is_presentation_form(ch: str) -> bool:
    return PRESENTATION_FORM_RANGE[0] <= ord(ch) <= PRESENTATION_FORM_RANGE[1]


def _is_c0_control(ch: str) -> bool:
    o = ord(ch)
    return (o < 0x20 and ch not in "\t\n\r") or o == 0x7F


def measure_text_health(page_text: str) -> TextHealth:
    """Classify the text layer of one page.

    ``page_text`` must come from the *text* extraction, never the words layer.
    """
    text_chars = len(page_text)
    arabic = sum(1 for c in page_text if _is_arabic(c))
    pres = sum(1 for c in page_text if _is_presentation_form(c))
    ctrl = sum(1 for c in page_text if _is_c0_control(c))
    repl = page_text.count(REPLACEMENT_CHAR)
    digits = sum(1 for c in page_text if c.isdigit())

    if ctrl > 0 and ctrl >= max(1, arabic + pres):
        regime = R1
    elif ctrl > 0 and arabic + pres == 0:
        regime = R1
    elif pres > 0:
        regime = R2
    elif arabic > 0:
        regime = R3 if _has_reversed_lamalef(page_text) else R3
    else:
        regime = R_HEALTHY_UNKNOWN

    # A page with substantial C0 substitution is R1 even if some Arabic survives.
    if ctrl >= 50 and regime != R1:
        regime = R1

    return TextHealth(
        text_chars=text_chars,
        arabic_chars=arabic,
        presentation_form_chars=pres,
        control_chars=ctrl,
        replacement_chars=repl,
        digit_chars=digits,
        encoding_regime=regime,
        arabic_recoverable=regime in (R2, R3),
    )


def _has_reversed_lamalef(text: str) -> bool:
    """Detect the R3 signature: an alef immediately followed by a lam."""
    for i in range(len(text) - 1):
        if text[i] in ALEF_FORMS and text[i + 1] == LAM:
            return True
    return False


# ---------------------------------------------------------------------- #
# Normalization
# ---------------------------------------------------------------------- #

NORM_NONE = "NONE"
NORM_NFKC = "NFKC_STRIP_TATWEEL_DIACRITICS"
NORM_LAMALEF = "NFKC_LAMALEF_TOLERANT"
NORM_UNRECOVERABLE = "UNRECOVERABLE_TEXT_REGIME"


def normalize_arabic(text: str) -> str:
    """NFKC + tatweel strip + diacritic strip + alef/ya/ta-marbuta folding.

    Deterministic and lossy only in ways that never change identity for the
    anchor vocabulary in use.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.replace(TATWEEL, "")
    s = ARABIC_DIACRITICS.sub("", s)
    s = (
        s.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
    )
    s = "".join(ch for ch in s if not _is_c0_control(ch))
    return re.sub(r"\s+", " ", s).strip()


#: The two characters whose *order* the R3 regime corrupts.
_LAMALEF_CHARS = frozenset({LAM, "ا"})


def lamalef_key(text: str) -> str:
    """Order-insensitive key for the lam-alef hazard.

    An R3 file stores the ligature ``لا`` with its two characters swapped, so
    ``الإيرادات`` arrives as ``اإليرادات``. What the regime corrupts is the
    *order of characters inside a run of lam and alef*, and nothing else — so
    the canonical form sorts each such run.

    Collapsing adjacent pairs instead (the obvious first attempt) does not work:
    a greedy scan pairs ``ا|لا`` and ``ال|ا`` differently and produces two
    different keys for the same word, which is exactly the failure this key
    exists to prevent.

    The cost is that two words differing *only* in the order of their lam and
    alef characters compare equal. That is what "lam-alef tolerant" means, and
    it is why this key corroborates a match but never decides one on its own.
    """
    s = normalize_arabic(text)
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] in _LAMALEF_CHARS:
            j = i
            while j < len(s) and s[j] in _LAMALEF_CHARS:
                j += 1
            out.append("".join(sorted(s[i:j])))
            i = j
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def charset_key(text: str) -> str:
    """Sorted character multiset of the normalized text.

    Used only as a *weak corroborating* signal: KB-ANCHORS-REGIMES is explicit
    that character coverage alone is not sufficient for anchor acceptance, so
    this never decides a match on its own.
    """
    return "".join(sorted(normalize_arabic(text).replace(" ", "")))


def strip_controls(text: str) -> str:
    return "".join(ch for ch in text if not _is_c0_control(ch))


def join_rtl(tokens: Iterable[tuple[float, str]]) -> str:
    """Join ``(x0, text)`` pairs in Arabic reading order (descending x)."""
    return " ".join(t for _, t in sorted(tokens, key=lambda z: -z[0])).strip()


def join_ltr(tokens: Iterable[tuple[float, str]]) -> str:
    """Join ``(x0, text)`` pairs left to right — the correct order for numbers."""
    return " ".join(t for _, t in sorted(tokens, key=lambda z: z[0])).strip()


def normalization_method_for(regime: str) -> str:
    if regime == R1:
        return NORM_UNRECOVERABLE
    if regime == R2:
        return NORM_NFKC
    if regime == R3:
        return NORM_LAMALEF
    return NORM_NONE


def decode_for_display(raw: str, regime: str) -> tuple[str, str, str]:
    """Return ``(decoded_text_ar, repair_status, repair_method)``.

    R1 text is never "repaired": the decoded field is left empty and the status
    says why, so a consumer can tell an unreadable source from an absent one.
    """
    if not raw:
        return "", "NO_TEXT", NORM_NONE
    if regime == R1:
        cleaned = strip_controls(raw).strip()
        if not cleaned or not any(_is_arabic(c) for c in cleaned):
            return "", "UNRECOVERABLE_R1_CONTROL_SUBSTITUTION", NORM_UNRECOVERABLE
        return cleaned, "PARTIAL_R1_SURVIVING_FRAGMENT", NORM_UNRECOVERABLE
    method = normalization_method_for(regime)
    return normalize_arabic(raw), "DETERMINISTIC_NORMALIZATION", method


def is_mojibake(text: str) -> bool:
    """Heuristic detector for double-encoded UTF-8 shown as Latin-1."""
    if not text:
        return False
    suspicious = sum(1 for c in text if c in "ÙØÃ¢â€™")
    return suspicious >= 3 and suspicious / max(1, len(text)) > 0.15
