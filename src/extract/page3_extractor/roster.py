"""Versioned T2 dam-roster registry.

Section 10 of the governing prompt requires a versioned roster registry with
validity periods and evidence, and forbids inferring a missing roster row as
zero. This module supplies the registry and a deterministic label matcher.

The registry is *seeded* from labels read on the manual ground-truth sample and
carries a per-entry ``evidence`` note. A label that does not match becomes a
``candidate`` with a confidence and a review-queue entry — never a silent
canonical id.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .text_and_encoding import R1, lamalef_key, normalize_arabic

ROSTER_REGISTRY_VERSION = "1.1.0"

#: An entry the Phase 3 ground-truth sample established and the Phase 4 audit
#: left standing.
STATUS_ACCEPTED = "ACCEPTED_PHASE3"

#: An entry added from measured corpus evidence whose *canonical id and English
#: name* a human has not yet confirmed. The Arabic label and the row's position
#: in the printed roster are measured; the Latin naming is corroborated only by
#: a PROVISIONAL reference snapshot that carries no decision authority. Facts
#: matched to such an entry are published with the dam_id **and** an explicit
#: review status, so the identity is usable and its provenance is never lost.
STATUS_CANDIDATE = "CANDIDATE_PENDING_HUMAN_CONFIRMATION"

REGISTRY_STATUSES = (STATUS_ACCEPTED, STATUS_CANDIDATE)


@dataclass(frozen=True)
class RosterEntry:
    dam_id: str
    name_ar: str
    name_en: str
    aliases: tuple[str, ...] = ()
    valid_from: str = ""
    valid_to: str = ""
    evidence: str = ""
    registry_status: str = STATUS_ACCEPTED


#: Seeded from labels read on the 24-file manual ground-truth sample across all
#: eras. ``valid_from`` / ``valid_to`` are left empty where the sample does not
#: bound them — an empty bound means "not measured", not "always".
SEED_ROSTER: tuple[RosterEntry, ...] = (
    RosterEntry("DAM-MELLEGUE", "ملاق", "Mellegue",
                ("ملاق (الى مستوى 265 م)", "مــالق"),
                evidence="GT sample rows, all eras"),
    RosterEntry("DAM-SIDI-SALEM", "سيدي سالم", "Sidi Salem",
                ("سيدي سالم (الى مستوى 115 م)", "سيدي ســالم"),
                evidence="GT sample rows, all eras"),
    RosterEntry("DAM-BOUHERTMA", "بوهرتمة", "Bouhertma",
                ("بو هرتمه", "بوهرتمه", "بو هرتمــه"),
                evidence="GT sample rows; spelling-variant crosswalk to the "
                         "reference name 'BOU HEURTMA' remains a CANDIDATE"),
    RosterEntry("DAM-JOUMINE", "جومين", "Joumine",
                ("جوميــن",), evidence="GT sample rows"),
    RosterEntry("DAM-SEJNANE", "سجنان", "Sejnane",
                ("سجنــان",), evidence="GT sample rows"),
    RosterEntry("DAM-SIDI-EL-BARRAK", "سيدي البراق", "Sidi El Barrak",
                (), evidence="GT sample rows (modern era)"),
    RosterEntry("DAM-SILIANA", "سليانة", "Siliana",
                ("سليانــة",), evidence="GT sample rows"),
    RosterEntry("DAM-BIR-MCHERGA", "بئر المشارقة", "Bir Mcherga",
                ("بئر المشارقـة",), evidence="GT sample rows"),
    RosterEntry("DAM-NEBHANA", "نبهانة", "Nebhana",
                (), evidence="GT sample rows"),
    RosterEntry("DAM-SIDI-SAAD", "سيدي سعد", "Sidi Saad",
                ("سيدي سعـد",), evidence="GT sample rows"),
    # 1.1.0: the canonical Arabic display label was the misspelt "الوارب" — the
    # ه of الهوارب was missing from the *registry seed*, not dropped by the
    # normalizer, so dam_candidate published a typo on every matched row while
    # dam_id stayed correct. The misspelling is kept as an alias so no key that
    # matched under 1.0.0 stops matching. Printed evidence: the label reads
    # "الهوارب" on the R2 pages where the text layer is legible
    # (e.g. 15-5-2022_3.pdf row label token 'ﺍﻟﻬﻭﺍﺭﺏ'), and the Milestone-1
    # snapshot names the dam 'El Houareb'.
    RosterEntry("DAM-EL-HOUAREB", "الهوارب", "El Houareb",
                ("الوارب",),
                evidence="GT sample rows (2014-2016 era); 1.1.0 corrected the "
                         "canonical name_ar from الوارب to الهوارب against the "
                         "printed label; الوارب retained as an alias"),
    # 1.1.0: added from measured corpus evidence. The row is printed between
    # بئر المشارقة and سيدي سعد on 379 files spanning 2022-06-17..2024-01-08,
    # with values, and was published as ROSTER_UNMATCHED throughout. The Latin
    # name is corroborated only by the PROVISIONAL Milestone-1 snapshot's dam
    # `hma` / "Hma" (decision authority NONE), so the entry is a CANDIDATE: the
    # dam_id is published and every matched fact carries an explicit review
    # status until a human confirms the id and the English name.
    RosterEntry("DAM-EL-HMA", "الحمى", "El Hma",
                (),
                valid_from="2022-06-17", valid_to="2024-01-08",
                evidence="379 corpus files 2022-06-17..2024-01-08, printed "
                         "between بئر المشارقة and سيدي سعد; crosswalk to the "
                         "reference name 'Hma' (dam_id `hma`) remains a "
                         "CANDIDATE — the snapshot is PROVISIONAL",
                registry_status=STATUS_CANDIDATE),
    RosterEntry("DAM-LAKHMESS", "لخمس", "Lakhmess",
                (), evidence="GT sample rows"),
    RosterEntry("DAM-BARBARA", "بربرة", "Barbara",
                (), evidence="T5 transfer labels"),
    RosterEntry("DAM-ZAYATIN", "الزياتين", "Zayatin",
                ("زياتين",),
                evidence="T5 transfer labels; crosswalk to reference 'ZIATINE' "
                         "remains a CANDIDATE"),
)


@dataclass
class RosterRegistry:
    version: str = ROSTER_REGISTRY_VERSION
    entries: tuple[RosterEntry, ...] = SEED_ROSTER
    _index: dict[str, RosterEntry] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        idx: dict[str, RosterEntry] = {}
        collisions: list[str] = []
        for e in self.entries:
            for name in (e.name_ar,) + tuple(e.aliases):
                k = _key(name)
                prior = idx.get(k)
                if prior is not None and prior.dam_id != e.dam_id:
                    collisions.append(f"{k!r}: {prior.dam_id} vs {e.dam_id}")
                idx[k] = e
        if collisions:
            # Two dams claiming one normalized key would make identity a
            # coin toss, so it is refused at construction rather than
            # published as a match.
            raise ValueError("roster alias collision: " + "; ".join(collisions))
        self._index = idx

    def lookup(self, key: str) -> Optional[RosterEntry]:
        return self._index.get(key)

    def as_rows(self) -> list[dict[str, str]]:
        return [
            {
                "roster_version": self.version,
                "dam_id": e.dam_id,
                "name_ar": e.name_ar,
                "name_en": e.name_en,
                "aliases": "|".join(e.aliases),
                "valid_from": e.valid_from,
                "valid_to": e.valid_to,
                "evidence": e.evidence,
                "registry_status": e.registry_status,
            }
            for e in self.entries
        ]

    @classmethod
    def from_csv(cls, path: Path) -> "RosterRegistry":
        entries: list[RosterEntry] = []
        version = ROSTER_REGISTRY_VERSION
        with open(path, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                version = row.get("roster_version") or version
                entries.append(RosterEntry(
                    row["dam_id"], row["name_ar"], row.get("name_en", ""),
                    tuple(a for a in (row.get("aliases") or "").split("|") if a),
                    row.get("valid_from", ""), row.get("valid_to", ""),
                    row.get("evidence", ""),
                    row.get("registry_status") or STATUS_ACCEPTED,
                ))
        return cls(version=version, entries=tuple(entries))


@dataclass(frozen=True)
class DamMatch:
    dam_id: str
    candidate: str
    name_en: str
    method: str
    confidence: Optional[float]
    registry_status: str = STATUS_ACCEPTED


NO_MATCH = DamMatch("", "", "", "NO_MATCH", 0.0)


def _key(name: str) -> str:
    return lamalef_key(normalize_arabic(name)).replace(" ", "")


def match_dam_label(label: str, roster: RosterRegistry, *, text_regime: str) -> DamMatch:
    """Match a printed row label to a roster entry.

    On R1 pages the label is control substitution, so no match is attempted and
    the row is published with an explicit unresolved identity rather than a
    guess.
    """
    if not label or not label.strip():
        return DamMatch("", "", "", "NO_LABEL", 0.0)
    if text_regime == R1:
        return DamMatch("", label.strip(), "", "TEXT_REGIME_R1_NOT_MATCHABLE", 0.0)

    key = _key(label)
    hit = roster.lookup(key)
    if hit:
        return DamMatch(hit.dam_id, hit.name_ar, hit.name_en, "EXACT_NORMALIZED", 1.0,
                        hit.registry_status)

    # Containment both ways covers the printed parentheticals
    # ("ملاق (الى مستوى 265 م)") without loosening into fuzzy matching.
    best: Optional[tuple[float, RosterEntry]] = None
    for e in roster.entries:
        for name in (e.name_ar,) + tuple(e.aliases):
            nk = _key(name)
            if not nk:
                continue
            if nk in key or key in nk:
                score = len(nk) / max(len(key), len(nk))
                if best is None or score > best[0]:
                    best = (score, e)
    if best and best[0] >= 0.5:
        return DamMatch(best[1].dam_id, best[1].name_ar, best[1].name_en,
                        "NORMALIZED_CONTAINMENT", round(best[0], 3),
                        best[1].registry_status)
    return DamMatch("", label.strip(), "", "NO_MATCH", 0.0)


#: PATCH-P5B-003. Set on a match made from the label column's own spans rather
#: than from the word stream, where tatweel elongation fragments the name and the
#: adjacent value welds into it.
MATCH_SPAN_LABEL = "SPAN_LABEL_NORMALISED"


def match_span_label(label: str, roster: RosterRegistry) -> DamMatch:
    """Match an assembled span label to the roster, **exactly or not at all**.

    Deliberately narrower than :func:`match_dam_label`: no containment fallback,
    no scored best guess. The span label is already normalised and already has
    its level qualifier and any welded digits removed, so a name that does not
    match a roster key exactly is a name the roster does not have — and saying
    so is more useful than a 0.5-confidence guess at a dam identity.
    """
    if not label or not label.strip():
        return DamMatch("", "", "", "NO_LABEL", 0.0)
    hit = roster.lookup(_key(label))
    if hit is None:
        return DamMatch("", label.strip(), "", "NO_EXACT_SPAN_LABEL_MATCH", 0.0)
    return DamMatch(hit.dam_id, hit.name_ar, hit.name_en, MATCH_SPAN_LABEL, 1.0,
                    hit.registry_status)


def default_registry(registry_root: Optional[Path] = None) -> RosterRegistry:
    if registry_root is not None:
        p = Path(registry_root) / "p3_t2_roster_registry.csv"
        if p.exists():
            return RosterRegistry.from_csv(p)
    return RosterRegistry()
