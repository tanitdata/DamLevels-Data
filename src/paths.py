"""Locations of inputs that live outside the repository.

Builders never hard-code machine paths. Each external input has a key; its
location comes from the environment variable ``DAMLEVELS_<KEY>`` or from the
``[paths]`` table of ``config/paths.local.toml`` (not tracked; copy
``config/paths.example.toml``). Paths written into published files use the
logical root tokens from ``ROOT_TOKENS`` instead of local drive letters.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = REPO / "config" / "paths.local.toml"

# Logical names for the external roots that appear in historical provenance.
# Order matters: longer prefixes first.
ROOT_TOKENS = [
    (r"<V010_REVIEW_PACKAGE>", "<V010_REVIEW_PACKAGE>"),
    (r"<FULL_RECONSTRUCTION>", "<FULL_RECONSTRUCTION>"),
    (r"<FROZEN_BASELINES>", "<FROZEN_BASELINES>"),
    (r"<REPO>", "<REPO>"),
    (r"<PFE_READY>", "<PFE_READY>"),
    (r"<PFE_WORK>", "<PFE_WORK>"),
    (r"<PFE_FINAL>", "<PFE_FINAL>"),
    (r"<TASK21>", "<TASK21>"),
    (r"<SATELLITE_DATA>", "<SATELLITE_DATA>"),
    (r"<PFE_SUBMITTABLE>", "<PFE_SUBMITTABLE>"),
    (r"<BULLETIN_CORPUS>", "<BULLETIN_CORPUS>"),
]


def _load_config() -> dict[str, str]:
    if not LOCAL_CONFIG.is_file():
        return {}
    with LOCAL_CONFIG.open("rb") as stream:
        return dict(tomllib.load(stream).get("paths", {}))


_CONFIG = _load_config()


def optional(key: str) -> Path | None:
    value = os.environ.get(f"DAMLEVELS_{key.upper()}") or _CONFIG.get(key)
    return Path(value) if value else None


def external(key: str) -> Path:
    path = optional(key)
    if path is None:
        raise KeyError(
            f"External input '{key}' is not configured. Set DAMLEVELS_{key.upper()} "
            f"or add it to {LOCAL_CONFIG.relative_to(REPO).as_posix()} "
            "(see config/paths.example.toml)."
        )
    return path


def portable(text: str) -> str:
    """Replace known local roots with logical tokens and use forward slashes."""
    for prefix, token in ROOT_TOKENS:
        for variant in (prefix, prefix.replace("\\", "/")):
            if variant in text:
                text = text.replace(variant, token)
    if "<" in text and "\\" in text:
        text = text.replace("\\", "/")
    return text
