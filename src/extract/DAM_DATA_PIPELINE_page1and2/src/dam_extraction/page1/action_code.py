from __future__ import annotations

import re

VALID_CODES = {"d", "e", "t", "p", "tr", "a", "f"}


def parse_action_code(raw: str) -> tuple[str | None, str]:
    text = raw.strip()
    if not text:
        return None, "SOURCE_BLANK"
    parts = [part for part in re.split(r"[,.;\s]+", text) if part]
    if parts and all(part.casefold() in VALID_CODES for part in parts):
        return ",".join(parts), "ACTION_CODE_PARSED"
    return None, "AMBIGUOUS_ACTION_CODE"

