from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DamRosterEntry:
    dam_id: str
    display_name: str
    region: str
    aliases: tuple[str, ...]


REGISTRY_PATH = Path(__file__).with_name("data") / "roster.json"
_REGISTRY_PAYLOAD = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
REGISTRY_VERSION = str(_REGISTRY_PAYLOAD["registry_version"])
ROSTER: tuple[DamRosterEntry, ...] = tuple(
    DamRosterEntry(
        dam_id=str(row["dam_id"]),
        display_name=str(row["display_name"]),
        region=str(row["region"]),
        aliases=tuple(str(alias) for alias in row["aliases"]),
    )
    for row in _REGISTRY_PAYLOAD["entries"]
)

BY_ID = {entry.dam_id: entry for entry in ROSTER}
ROSTER_INDEX = {entry.dam_id: index for index, entry in enumerate(ROSTER)}


def deduplicate_doubled_token(text: str) -> str:
    if len(text) < 4 or len(text) % 2:
        return text
    pairs = [text[index:index + 2] for index in range(0, len(text), 2)]
    if all(len(pair) == 2 and pair[0] == pair[1] for pair in pairs):
        return "".join(pair[0] for pair in pairs)
    return text


def normalize_label(text: str) -> str:
    text = " ".join(deduplicate_doubled_token(token) for token in str(text or "").split())
    text = unicodedata.normalize("NFKD", text)
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


ALIAS_TO_ID: dict[str, str] = {}
for _entry in ROSTER:
    for _alias in _entry.aliases:
        normalized = normalize_label(_alias)
        previous = ALIAS_TO_ID.get(normalized)
        if previous is not None and previous != _entry.dam_id:
            raise ValueError(f"Conflicting governed alias {normalized!r}: {previous} vs {_entry.dam_id}")
        ALIAS_TO_ID[normalized] = _entry.dam_id


def identify_text_label(raw_text: str) -> str | None:
    normalized = normalize_label(raw_text)
    return ALIAS_TO_ID.get(normalized)


def expected_single_between(previous_dam: str | None, next_dam: str | None) -> str | None:
    if previous_dam is None or next_dam is None:
        return None
    previous_index = ROSTER_INDEX[previous_dam]
    next_index = ROSTER_INDEX[next_dam]
    if next_index - previous_index == 2:
        return ROSTER[previous_index + 1].dam_id
    return None


def region_for(dam_id: str) -> str:
    return BY_ID[dam_id].region
