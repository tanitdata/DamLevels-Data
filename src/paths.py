"""Locations of inputs that live outside the repository.

Builders never hard-code machine paths. Each external input has a key; its
location comes from the environment variable ``DAMLEVELS_<KEY>`` or from the
``[paths]`` table of ``config/paths.local.toml`` (not tracked; copy
``config/paths.example.toml``). Paths written into published files use the
logical root tokens (``<FULL_RECONSTRUCTION>``, ``<BULLETIN_CORPUS>``, ...) instead
of local drive letters; which local folder each token stands for is set in the
same untracked config, never in this file.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = REPO / "config" / "paths.local.toml"


def _load_config() -> dict:
    if not LOCAL_CONFIG.is_file():
        return {}
    with LOCAL_CONFIG.open("rb") as stream:
        return tomllib.load(stream)


def _root_tokens(config: dict) -> list[tuple[str, str]]:
    """(local prefix, logical token) pairs, longest prefix first.

    Local roots are machine-specific, so they are never written in the code: they
    come from the ``[roots]`` table of the local config (``"<TOKEN>" = "local path"``)
    or from ``DAMLEVELS_ROOT_<NAME>`` environment variables for the token ``<NAME>``.
    """
    roots = {token: path for token, path in config.get("roots", {}).items() if path}
    for name, value in os.environ.items():
        if name.startswith("DAMLEVELS_ROOT_") and value:
            roots[f"<{name[len('DAMLEVELS_ROOT_'):]}>"] = value
    roots.setdefault("<REPO>", str(REPO))
    return sorted(((path, token) for token, path in roots.items()), key=lambda item: -len(item[0]))


_FILE_CONFIG = _load_config()
_CONFIG = dict(_FILE_CONFIG.get("paths", {}))
ROOT_TOKENS = _root_tokens(_FILE_CONFIG)


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
        for variant in (prefix, prefix.replace("\\", "/"), prefix.replace("/", "\\")):
            if variant in text:
                text = text.replace(variant, token)
    if "<" in text and "\\" in text:
        text = text.replace("\\", "/")
    return text
