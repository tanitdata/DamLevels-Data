"""Anchor detection, adjudication and unit markers.

Section 12 of the governing prompt: the old exploratory anchor CSVs are not a
production registry. Six separate layers are produced here, and every attempt
ends in exactly one terminal status:

``anchor_attempt``        one row per (file, anchor definition) — always emitted
``anchor_candidate``      each text span that scored above the floor
``anchor_adjudication``   which candidate won, and why
``anchor_variant_registry`` accepted normalized spellings, versioned
``anchor_fragment_link``  accepted anchor -> fragment, with the distance gate
``anchor_review_queue``   attempts that need a human
``unit_marker_inventory`` unit notes, which are **not** routing anchors

Acceptance combines normalized text, required tokens, prohibited tokens, layout
family, semantic slot, canonical coordinates, a distance gate and text-regime
compatibility. Character coverage alone never accepts a candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from .geometry import Fragment, Word, horizontal_overlap, vertical_gap
from .text_and_encoding import (
    R1,
    TATWEEL,
    charset_key,
    lamalef_key,
    normalize_arabic,
)

ANCHOR_REGISTRY_VERSION = "1.1.0"

# --- terminal statuses --------------------------------------------------- #
ACCEPTED = "ACCEPTED"
REJECTED_NO_CANDIDATE = "REJECTED_NO_CANDIDATE"
REJECTED_PROHIBITED_TOKEN = "REJECTED_PROHIBITED_TOKEN"
REJECTED_DISTANCE_GATE = "REJECTED_DISTANCE_GATE"
REJECTED_BELOW_THRESHOLD = "REJECTED_BELOW_THRESHOLD"
AMBIGUOUS_REVIEW = "AMBIGUOUS_MULTIPLE_CANDIDATES"
TEXT_REGIME_INCOMPATIBLE = "TEXT_REGIME_INCOMPATIBLE"

ANCHOR_STATUSES = (
    ACCEPTED,
    REJECTED_NO_CANDIDATE,
    REJECTED_PROHIBITED_TOKEN,
    REJECTED_DISTANCE_GATE,
    REJECTED_BELOW_THRESHOLD,
    AMBIGUOUS_REVIEW,
    TEXT_REGIME_INCOMPATIBLE,
)


@dataclass(frozen=True)
class AnchorDef:
    """One section anchor and everything acceptance needs."""

    anchor_id: str
    section_id: str
    canonical_text: str
    required_tokens: tuple[str, ...]
    prohibited_tokens: tuple[str, ...] = ()
    target_fragment_rank: Optional[int] = None
    max_gap_above: float = 40.0
    allow_inside_fragment: bool = False
    is_unit_marker: bool = False
    min_score: float = 0.62


#: Titles sit outside/above their fragment (6-20 pt typically); T2 and T5 print
#: theirs inside the fragment's header band, so those two allow containment.
ANCHOR_DEFS: tuple[AnchorDef, ...] = (
    AnchorDef("A0-PAGE-TITLE", "PAGE",
              "ملاحظات حول الوضعية المائية ليوم",
              required_tokens=("الوضعية", "المائية"),
              prohibited_tokens=(),
              target_fragment_rank=None, max_gap_above=1e9),
    AnchorDef("A1-T1-TITLE", "T1",
              "المخزون بالسدود",
              required_tokens=("المخزون",),
              prohibited_tokens=("توزيع",),
              target_fragment_rank=1, max_gap_above=45.0),
    AnchorDef("A2-T2-TITLE", "T2",
              "توزيع المخزون بأهم السدود",
              required_tokens=("توزيع", "المخزون"),
              prohibited_tokens=(),
              target_fragment_rank=2, max_gap_above=45.0,
              allow_inside_fragment=True),
    AnchorDef("A3-T3-TITLE", "T3",
              "الإيرادات الجملية للسدود",
              required_tokens=("الايرادات",),
              prohibited_tokens=("الاستعمالات", "السحب"),
              target_fragment_rank=3, max_gap_above=45.0),
    AnchorDef("A4-T4-TITLE", "T4",
              "مجموع الاستعمالات والسحب",
              required_tokens=("الاستعمالات",),
              prohibited_tokens=("الايرادات",),
              target_fragment_rank=6, max_gap_above=45.0),
    AnchorDef("A5-T5-TITLE", "T5",
              "تحويل المياه باعتماد الضخ",
              required_tokens=("تحويل", "الضخ"),
              # A transfer title must never be matched by flood-protection
              # vocabulary (section 12 of the governing prompt).
              prohibited_tokens=("الفيضانات", "الحماية", "التصريف"),
              target_fragment_rank=8, max_gap_above=45.0,
              allow_inside_fragment=True),
    AnchorDef("A6-T6-TITLE", "T6",
              "تغذية بحيرة اشكل",
              required_tokens=("بحيره", "اشكل"),
              prohibited_tokens=("سد",),
              target_fragment_rank=9, max_gap_above=45.0),
)

UNIT_MARKER_DEFS: tuple[AnchorDef, ...] = (
    AnchorDef("U1-MILLION-M3", "UNIT", "مليون م3",
              required_tokens=("مليون",), is_unit_marker=True,
              target_fragment_rank=None, max_gap_above=1e9),
    AnchorDef("U2-PERCENT", "UNIT", "%", required_tokens=("%",),
              is_unit_marker=True, target_fragment_rank=None, max_gap_above=1e9),
)


@dataclass
class AnchorCandidate:
    anchor_id: str
    section_id: str
    raw_text: str
    normalized_text: str
    bbox: tuple[float, float, float, float]
    score: float
    match_method: str
    required_hits: int
    prohibited_hits: tuple[str, ...] = ()


@dataclass
class AnchorAttempt:
    anchor_id: str
    section_id: str
    text_regime: str
    status: str
    reason: str
    candidate_count: int
    best_candidate: Optional[AnchorCandidate] = None
    linked_fragment_rank: Optional[int] = None
    link_gap: Optional[float] = None
    link_method: str = ""


@dataclass
class AnchorResult:
    attempts: list[AnchorAttempt] = field(default_factory=list)
    candidates: list[AnchorCandidate] = field(default_factory=list)
    unit_markers: list[AnchorCandidate] = field(default_factory=list)
    variants: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def accepted_sections(self) -> set[str]:
        return {a.section_id for a in self.attempts if a.status == ACCEPTED}

    def status_for(self, anchor_id: str) -> str:
        for a in self.attempts:
            if a.anchor_id == anchor_id:
                return a.status
        return REJECTED_NO_CANDIDATE


# ---------------------------------------------------------------------- #

def _join_anchor_line(ordered: Sequence[Word]) -> str:
    """Join one visual line, healing the tatweel-token split (PATCH-P4-004).

    Tatweel (U+0640) elongates a letter so it reaches the next letter of the
    *same* word. On presentation-form pages PyMuPDF emits a tatweel run as its
    own word token, so a plain space join turns ``الضـخ`` into ``الض ـ خ``.
    ``normalize_arabic`` then strips the tatweel but leaves the space, and the
    exact-substring match for ``تحويل المياه باعتماد الضخ`` fails on all 343 R2
    pages while the other six anchors match — which is AUD-F-010 / PATCH-P4-004.

    A tatweel is a within-word glyph, never a word boundary, so a token that is
    nothing but tatweel is dropped and its neighbours are joined seamlessly, as
    is any pair where one side ends and the other begins with one.
    """
    parts: list[str] = []
    glue_next = False
    for w in ordered:
        text = w.text or ""
        if text and all(ch == TATWEEL for ch in text):
            glue_next = True
            continue
        if parts and (glue_next or text.startswith(TATWEEL)
                      or parts[-1].endswith(TATWEEL)):
            parts[-1] = parts[-1] + text
        else:
            parts.append(text)
        glue_next = text.endswith(TATWEEL)
    return " ".join(parts).strip()


def _line_spans(words: Sequence[Word], y_tol: float = 3.0) -> list[tuple[list[Word], str]]:
    """Group words into visual lines and join each right-to-left."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (round(w.y0, 1), w.x0)):
        if lines and abs(lines[-1][0].y0 - w.y0) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    out = []
    for ln in lines:
        ordered = sorted(ln, key=lambda w: -w.x0)
        out.append((ordered, _join_anchor_line(ordered)))
    return out


def _span_bbox(words: Sequence[Word]) -> tuple[float, float, float, float]:
    return (min(w.x0 for w in words), min(w.y0 for w in words),
            max(w.x1 for w in words), max(w.y1 for w in words))


def _contains_token(haystack_norm: str, haystack_key: str, token: str) -> bool:
    """Token containment that survives the lam-alef hazard.

    A token such as ``الاستعمالات`` carries a lam-alef pair, which an R3 file
    stores reversed. Testing only the normalized form would fail on every R3
    page — which is precisely the regime where anchors are otherwise readable —
    so the tolerant key is checked as well. Both sides go through the same key,
    so this loosens nothing that plain normalization would have caught.
    """
    t_norm = normalize_arabic(token)
    if t_norm and t_norm in haystack_norm:
        return True
    t_key = lamalef_key(token)
    return bool(t_key) and t_key in haystack_key


def _score(defn: AnchorDef, text: str) -> tuple[float, str, int, tuple[str, ...]]:
    """Score one line against one anchor definition.

    Returns ``(score, method, required_hits, prohibited_hits)``. Prohibited
    tokens veto regardless of score.
    """
    norm = normalize_arabic(text)
    key = lamalef_key(text)
    canon = normalize_arabic(defn.canonical_text)
    prohibited = tuple(t for t in defn.prohibited_tokens
                       if _contains_token(norm, key, t))
    required_hits = sum(1 for t in defn.required_tokens
                        if _contains_token(norm, key, t))

    if canon and canon in norm:
        return 1.0, "EXACT_NORMALIZED_SUBSTRING", required_hits, prohibited

    lk_canon = lamalef_key(defn.canonical_text)
    if lk_canon and lk_canon in key:
        return 0.95, "LAMALEF_TOLERANT_SUBSTRING", required_hits, prohibited

    if defn.required_tokens:
        frac = required_hits / len(defn.required_tokens)
        if frac >= 1.0:
            return 0.9, "ALL_REQUIRED_TOKENS", required_hits, prohibited
        if frac > 0:
            # A partial token hit is corroboration only; never enough alone.
            cover = _charset_coverage(text, defn.canonical_text)
            return 0.4 * frac + 0.2 * cover, "PARTIAL_TOKENS_PLUS_CHARSET", required_hits, prohibited

    return 0.0, "NO_MATCH", required_hits, prohibited


def _charset_coverage(text: str, canonical: str) -> float:
    a, b = charset_key(text), charset_key(canonical)
    if not b:
        return 0.0
    from collections import Counter

    ca, cb = Counter(a), Counter(b)
    hit = sum(min(cb[ch], ca.get(ch, 0)) for ch in cb)
    return hit / sum(cb.values())


def detect_anchors(words: Sequence[Word],
                   fragments: Sequence[Fragment],
                   text_regime: str) -> AnchorResult:
    """Run every anchor definition and record a terminal status for each."""
    result = AnchorResult()
    lines = _line_spans(words)

    for defn in ANCHOR_DEFS:
        if text_regime == R1:
            # R1 Arabic is unrecoverable from the text layer. Recording the
            # attempt as regime-incompatible keeps an absent anchor from
            # implying an absent section (governing prompt section 9).
            result.attempts.append(AnchorAttempt(
                defn.anchor_id, defn.section_id, text_regime,
                TEXT_REGIME_INCOMPATIBLE,
                "R1 control substitution: text anchors are not evidence here; "
                "section presence is decided by verified geometry",
                candidate_count=0,
            ))
            continue

        cands: list[AnchorCandidate] = []
        for span_words, text in lines:
            score, method, req, prohibited = _score(defn, text)
            if score <= 0.0 and not prohibited:
                continue
            cands.append(AnchorCandidate(
                defn.anchor_id, defn.section_id, text, normalize_arabic(text),
                _span_bbox(span_words), round(score, 4), method, req, prohibited,
            ))
        result.candidates.extend(cands)

        viable = [c for c in cands if not c.prohibited_hits and c.score >= defn.min_score]
        # Only a candidate that *would otherwise have been accepted* counts as a
        # prohibited-token rejection. A line that merely contains a prohibited
        # word — the neighbouring section's title, say — was never a contender,
        # and reporting it as "found and rejected" would claim the anchor was
        # located when it was not.
        vetoed = [c for c in cands if c.prohibited_hits and c.score >= defn.min_score]

        if not viable:
            status = REJECTED_PROHIBITED_TOKEN if vetoed else REJECTED_NO_CANDIDATE
            reason = (f"the only candidates above the score floor were vetoed by "
                      f"{sorted({t for c in vetoed for t in c.prohibited_hits})}"
                      if vetoed else "no candidate reached the score floor")
            result.attempts.append(AnchorAttempt(
                defn.anchor_id, defn.section_id, text_regime, status, reason, len(cands),
            ))
            continue

        viable.sort(key=lambda c: (-c.score, c.bbox[1]))
        best = viable[0]
        runner = viable[1] if len(viable) > 1 else None
        if runner is not None and abs(runner.score - best.score) < 1e-9 and best.score < 0.95:
            # A tie on text alone is not yet ambiguity. The definition already
            # declares which fragment this anchor belongs to and how far above it
            # a title may sit; using that gate to separate tied candidates is
            # what it is for. Only a tie that survives the gate is ambiguous.
            tied = [c for c in viable if abs(c.score - best.score) < 1e-9]
            linked = [(c, _link_to_fragment(defn, c, fragments)) for c in tied]
            on_target = [(c, link) for c, link in linked
                         if link[0] is not None
                         and (defn.target_fragment_rank is None
                              or link[0] == defn.target_fragment_rank)]
            if len(on_target) != 1:
                result.attempts.append(AnchorAttempt(
                    defn.anchor_id, defn.section_id, text_regime, AMBIGUOUS_REVIEW,
                    f"{len(tied)} candidates tied at score {best.score}; "
                    f"{len(on_target)} of them satisfy the distance gate to "
                    f"fragment {defn.target_fragment_rank}",
                    len(cands), best,
                ))
                continue
            best = on_target[0][0]

        rank, gap, link_method = _link_to_fragment(defn, best, fragments)
        if defn.target_fragment_rank is not None and rank is None:
            result.attempts.append(AnchorAttempt(
                defn.anchor_id, defn.section_id, text_regime, REJECTED_DISTANCE_GATE,
                f"no fragment within {defn.max_gap_above} pt below the candidate",
                len(cands), best,
            ))
            continue

        result.attempts.append(AnchorAttempt(
            defn.anchor_id, defn.section_id, text_regime, ACCEPTED,
            f"score {best.score} via {best.match_method}", len(cands), best,
            rank, gap, link_method,
        ))
        result.variants.append((defn.anchor_id, best.normalized_text, best.match_method))

    for defn in UNIT_MARKER_DEFS:
        if text_regime == R1 and defn.anchor_id != "U2-PERCENT":
            continue
        for span_words, text in lines:
            score, method, _req, prohibited = _score(defn, text)
            if score >= defn.min_score and not prohibited:
                result.unit_markers.append(AnchorCandidate(
                    defn.anchor_id, "UNIT", text, normalize_arabic(text),
                    _span_bbox(span_words), round(score, 4), method, 1,
                ))
    return result


def _link_to_fragment(defn: AnchorDef,
                      cand: AnchorCandidate,
                      fragments: Sequence[Fragment]):
    """Link an accepted anchor to its fragment through the distance gate."""
    if defn.target_fragment_rank is None:
        return None, None, "NO_TARGET"

    best_rank, best_gap, method = None, None, ""
    for frag in fragments:
        overlap = horizontal_overlap(cand.bbox, frag.bbox)
        if overlap <= 0:
            continue
        if defn.allow_inside_fragment and _inside(frag.bbox, cand.bbox):
            return frag.index, 0.0, "CONTAINED_IN_FRAGMENT_HEADER"
        gap = vertical_gap(cand.bbox, frag.bbox)
        if 0 <= gap <= defn.max_gap_above and (best_gap is None or gap < best_gap):
            best_rank, best_gap, method = frag.index, gap, "NEAREST_FRAGMENT_BELOW"
    return best_rank, best_gap, method


def _inside(outer, inner, pad: float = 2.0) -> bool:
    return (outer[1] - pad <= inner[1] and inner[3] <= outer[3] + pad
            and outer[0] - pad <= inner[0] and inner[2] <= outer[2] + pad)


def anchor_confirms(result: AnchorResult, section_id: str, fragment_rank: int) -> str:
    """How strongly the anchors corroborate a positional fragment assignment."""
    for a in result.attempts:
        if a.section_id != section_id:
            continue
        if a.status == ACCEPTED and a.linked_fragment_rank == fragment_rank:
            return "ANCHOR_CONFIRMED"
        if a.status == ACCEPTED:
            return "ANCHOR_CONFLICT"
        if a.status == TEXT_REGIME_INCOMPATIBLE:
            return "ANCHOR_UNAVAILABLE_TEXT_REGIME"
        return "ANCHOR_NOT_FOUND"
    return "ANCHOR_NOT_ATTEMPTED"
