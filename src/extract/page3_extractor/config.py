"""Run configuration.

Contract (governing prompt section 5): a user changes only ``input_dir``,
``output_root``, ``mode``, ``reference_snapshot`` and ``resume``. Every path is
accepted through the Python API, a YAML file, the CLI, or the notebook cell —
and **no module carries the producer's absolute paths as a required default**.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .version import (
    EXTRACTOR_VERSION,
    ROUTING_VERSION,
    SEMANTICS_VERSION,
    SCHEMA_CONTRACT_VERSION,
)

MODES = ("quick_check", "benchmark", "full", "review_existing_run")

#: Sampling sizes used by the non-``full`` modes. ``benchmark`` uses the
#: deterministic stratified sample described in :mod:`page3_extractor.sampling`.
DEFAULT_QUICK_CHECK_FILES = 10
DEFAULT_BENCHMARK_FILES = 200


class ConfigError(ValueError):
    """Raised for a configuration that cannot produce a defensible run."""


@dataclass(frozen=True)
class Page3RunConfig:
    """User-facing configuration.

    Parameters
    ----------
    input_dir:
        Directory of Page 3 PDFs. Read-only: the extractor never writes,
        renames or deletes anything under it.
    output_root:
        Directory that will receive ``runs/<run_id>/``. Created if absent.
    mode:
        One of :data:`MODES`.
    reference_snapshot:
        Optional directory or CSV of a *frozen* reference snapshot for
        diagnostic comparison. ``None`` disables the comparison layer entirely
        (the comparison tables are still emitted, empty, with headers).
    resume:
        Reuse an interrupted run directory with the same ``run_id`` instead of
        starting a new one. A *completed* run is never overwritten.
    """

    input_dir: Path
    output_root: Path
    mode: str = "quick_check"
    reference_snapshot: Optional[Path] = None
    resume: bool = True

    # --- everything below has a safe default; users rarely touch it ---------
    run_id: Optional[str] = None
    sample_size: Optional[int] = None
    file_list: Optional[tuple[str, ...]] = None
    workers: int = 1
    schema_root: Optional[Path] = None
    registry_root: Optional[Path] = None
    cache_dir: Optional[Path] = None
    enable_cache: bool = False
    checkpoint_every: int = 100
    fail_fast: bool = False
    emit_publication_exports: bool = True
    emit_findings: bool = False
    comparison_rules_enabled: bool = False
    label: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def __post_init__(self) -> None:
        object.__setattr__(self, "input_dir", Path(self.input_dir))
        object.__setattr__(self, "output_root", Path(self.output_root))
        if self.reference_snapshot is not None:
            object.__setattr__(self, "reference_snapshot", Path(self.reference_snapshot))
        for name in ("schema_root", "registry_root", "cache_dir"):
            v = getattr(self, name)
            if v is not None:
                object.__setattr__(self, name, Path(v))
        if self.mode not in MODES:
            raise ConfigError(f"mode must be one of {MODES}, got {self.mode!r}")
        if self.workers < 1:
            raise ConfigError("workers must be >= 1")
        if self.workers > 6:
            # RAM-bound limit measured in EXTRACTOR_PERFORMANCE_ARCHITECTURE_DECISION section 2.5.
            raise ConfigError(
                "workers > 6 is refused: the accepted architecture caps parallelism at "
                "4-6 processes (RAM-bound). Raise it only with a new measurement."
            )

    # ------------------------------------------------------------------ #
    def with_(self, **kw: Any) -> "Page3RunConfig":
        """Return a copy with fields replaced (configs are frozen)."""
        return replace(self, **kw)

    @property
    def effective_sample_size(self) -> Optional[int]:
        if self.sample_size is not None:
            return self.sample_size
        if self.mode == "quick_check":
            return DEFAULT_QUICK_CHECK_FILES
        if self.mode == "benchmark":
            return DEFAULT_BENCHMARK_FILES
        return None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, Path):
                d[k] = str(v)
        if d.get("file_list") is not None:
            d["file_list"] = list(d["file_list"])
        return d


@dataclass(frozen=True)
class ResolvedConfig:
    """Config plus the derived identity a run is accountable to."""

    config: Page3RunConfig
    run_id: str
    run_dir: Path
    configuration_hash: str
    created_at: str
    environment: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "configuration_hash": self.configuration_hash,
            "created_at": self.created_at,
            "extractor_version": EXTRACTOR_VERSION,
            "routing_version": ROUTING_VERSION,
            "semantics_version": SEMANTICS_VERSION,
            "schema_contract_version": SCHEMA_CONTRACT_VERSION,
            "config": self.config.to_dict(),
        }


# ---------------------------------------------------------------------- #
# Configuration hashing
# ---------------------------------------------------------------------- #

#: Fields that change *what* is produced. Fields that only change *how fast* or
#: *where* it is produced are deliberately excluded so that a rerun in a
#: different folder still reports the same configuration hash.
SEMANTIC_CONFIG_FIELDS = (
    "mode",
    "sample_size",
    "file_list",
    "comparison_rules_enabled",
    "emit_publication_exports",
)


def configuration_hash(cfg: Page3RunConfig) -> str:
    """Stable hash over the *semantic* configuration and the code versions."""
    payload = {
        "extractor_version": EXTRACTOR_VERSION,
        "routing_version": ROUTING_VERSION,
        "semantics_version": SEMANTICS_VERSION,
        "schema_contract_version": SCHEMA_CONTRACT_VERSION,
        "config": {k: cfg.to_dict().get(k) for k in SEMANTIC_CONFIG_FIELDS},
        "reference_snapshot_supplied": cfg.reference_snapshot is not None,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def environment_fingerprint() -> dict[str, Any]:
    """Package and interpreter versions actually in use, recorded per run."""
    versions: dict[str, str] = {}
    for mod, attr in (
        ("fitz", "__doc__"),
        ("pdfplumber", "__version__"),
        ("pypdf", "__version__"),
        ("numpy", "__version__"),
        ("pandas", "__version__"),
    ):
        try:  # pragma: no cover - environment dependent
            m = __import__(mod)
            if mod == "fitz":
                versions["pymupdf"] = getattr(m, "VersionBind", getattr(m, "__version__", "unknown"))
            else:
                versions[mod] = str(getattr(m, attr, "unknown"))
        except Exception as exc:  # noqa: BLE001
            versions[mod] = f"UNAVAILABLE: {type(exc).__name__}"
    return {
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "packages": versions,
        "extractor_version": EXTRACTOR_VERSION,
        "routing_version": ROUTING_VERSION,
        "semantics_version": SEMANTICS_VERSION,
        "schema_contract_version": SCHEMA_CONTRACT_VERSION,
    }


def make_run_id(cfg: Page3RunConfig, now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d_%H%M%S")
    suffix = f"_{cfg.label}" if cfg.label else ""
    return f"RUN-P3-{cfg.mode.upper()}-{stamp}{suffix}"


def resolve_config(cfg: Page3RunConfig, now: Optional[datetime] = None) -> ResolvedConfig:
    """Validate paths, mint (or reuse) the run id, and freeze the identity."""
    if not cfg.input_dir.exists():
        raise ConfigError(f"input_dir does not exist: {cfg.input_dir}")
    if not cfg.input_dir.is_dir():
        raise ConfigError(f"input_dir is not a directory: {cfg.input_dir}")
    if cfg.reference_snapshot is not None and not cfg.reference_snapshot.exists():
        raise ConfigError(f"reference_snapshot does not exist: {cfg.reference_snapshot}")

    run_id = cfg.run_id or make_run_id(cfg, now)
    run_dir = cfg.output_root / "runs" / run_id

    status_file = run_dir / "RUN_STATUS.json"
    if status_file.exists():
        status = json.loads(status_file.read_text(encoding="utf-8"))
        if status.get("status") == "COMPLETED" and not cfg.resume:
            raise ConfigError(
                f"run {run_id} is already COMPLETED; refusing to overwrite a completed run"
            )
        if status.get("status") == "COMPLETED" and cfg.resume:
            raise ConfigError(
                f"run {run_id} is already COMPLETED; resume is only for interrupted runs"
            )

    return ResolvedConfig(
        config=cfg,
        run_id=run_id,
        run_dir=run_dir,
        configuration_hash=configuration_hash(cfg),
        created_at=(now or datetime.now(timezone.utc)).isoformat(),
        environment=environment_fingerprint(),
    )


# ---------------------------------------------------------------------- #
# YAML
# ---------------------------------------------------------------------- #

_YAML_PATH_KEYS = {
    "input_dir",
    "output_root",
    "reference_snapshot",
    "schema_root",
    "registry_root",
    "cache_dir",
}


def load_config(path: str | os.PathLike[str], overrides: Optional[dict[str, Any]] = None) -> Page3RunConfig:
    """Build a :class:`Page3RunConfig` from a YAML file.

    ``PyYAML`` is optional: a small key/value reader handles the flat schema the
    shipped configs use, so the package installs and runs without it.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    data = _parse_yaml(text)
    data.update(overrides or {})

    unknown = set(data) - {f for f in Page3RunConfig.__dataclass_fields__}
    if unknown:
        raise ConfigError(f"unknown configuration keys in {p}: {sorted(unknown)}")

    for k in list(data):
        if k in _YAML_PATH_KEYS and data[k] is not None:
            data[k] = Path(str(data[k])).expanduser()
    if isinstance(data.get("file_list"), list):
        data["file_list"] = tuple(data["file_list"])
    return Page3RunConfig(**data)


def _parse_yaml(text: str) -> dict[str, Any]:
    try:  # pragma: no cover - depends on environment
        import yaml  # type: ignore

        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ConfigError("configuration file must contain a mapping at the top level")
        return {k: v for k, v in loaded.items() if not str(k).startswith("_")}
    except ImportError:
        return _parse_flat_yaml(text)


def _parse_flat_yaml(text: str) -> dict[str, Any]:
    """Minimal flat ``key: value`` / ``- item`` reader (PyYAML-free fallback)."""
    out: dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for raw in text.splitlines():
        line = raw.split(" #")[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and current_list_key:
            out.setdefault(current_list_key, []).append(_scalar(line.lstrip()[2:].strip()))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key.startswith("_"):
            current_list_key = None
            continue
        if value == "":
            current_list_key = key
            out[key] = []
        else:
            current_list_key = None
            out[key] = _scalar(value)
    return {k: v for k, v in out.items() if v != [] or k == "file_list"}


def _scalar(v: str) -> Any:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    low = v.lower()
    if low in ("null", "none", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def default_schema_root(cfg: Page3RunConfig) -> Optional[Path]:
    """Schema root: explicit config wins, else the copy shipped in the package."""
    if cfg.schema_root is not None:
        return cfg.schema_root
    packaged = Path(__file__).resolve().parent / "contracts" / "schemas"
    return packaged if packaged.is_dir() else None


def default_registry_root(cfg: Page3RunConfig) -> Path:
    if cfg.registry_root is not None:
        return cfg.registry_root
    return Path(__file__).resolve().parent / "contracts" / "registries"


def iter_config_paths(cfg: Page3RunConfig) -> Iterable[tuple[str, Optional[Path]]]:
    yield "input_dir", cfg.input_dir
    yield "output_root", cfg.output_root
    yield "reference_snapshot", cfg.reference_snapshot
    yield "schema_root", default_schema_root(cfg)
    yield "registry_root", default_registry_root(cfg)
