"""Command-line interface.

The CLI and the notebook call the same Python API — there is no logic here that
a notebook user cannot reach, and none that a CLI user cannot.

    python -m page3_extractor run      --config path\\to\\config.yaml
    python -m page3_extractor run      --input-dir DIR --output-root DIR --mode quick_check
    python -m page3_extractor validate --run-dir path\\to\\run
    python -m page3_extractor review   --run-dir path\\to\\run
    python -m page3_extractor findings --run-dir path\\to\\run
    python -m page3_extractor benchmark --input-dir DIR --output-root DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .config import Page3RunConfig, load_config
from .version import EXTRACTOR_VERSION, RELEASE_STATUS


def _add_config_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="YAML configuration file")
    p.add_argument("--input-dir", help="directory of Page 3 PDFs (read-only)")
    p.add_argument("--output-root", help="directory that receives runs/<run_id>/")
    p.add_argument("--mode", choices=("quick_check", "benchmark", "full",
                                      "review_existing_run"))
    p.add_argument("--reference-snapshot", default=None,
                   help="frozen reference snapshot directory or CSV (diagnostic only)")
    p.add_argument("--sample-size", type=int, default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--label", default=None)
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--no-resume", action="store_true")
    p.add_argument("--fail-fast", action="store_true")
    p.add_argument("--schema-root", default=None)
    p.add_argument("--registry-root", default=None)
    p.add_argument("--file", action="append", dest="files", default=None,
                   help="restrict the run to this file name; repeatable")


def _build_config(args: argparse.Namespace) -> Page3RunConfig:
    overrides: dict[str, object] = {}
    for name in ("input_dir", "output_root", "mode", "reference_snapshot",
                 "sample_size", "run_id", "label", "workers", "schema_root",
                 "registry_root"):
        v = getattr(args, name, None)
        if v is not None:
            overrides[name] = v
    if getattr(args, "files", None):
        overrides["file_list"] = tuple(args.files)
    if getattr(args, "no_resume", False):
        overrides["resume"] = False
    if getattr(args, "fail_fast", False):
        overrides["fail_fast"] = True

    if args.config:
        return load_config(args.config, overrides)
    missing = [k for k in ("input_dir", "output_root") if k not in overrides]
    if missing:
        raise SystemExit(
            f"error: --config or both --input-dir and --output-root are required "
            f"(missing {', '.join(missing)})"
        )
    for k in ("input_dir", "output_root", "reference_snapshot", "schema_root",
              "registry_root"):
        if overrides.get(k) is not None:
            overrides[k] = Path(str(overrides[k])).expanduser()
    return Page3RunConfig(**overrides)  # type: ignore[arg-type]


def _progress(i: int, total: int, name: str, status: str) -> None:
    if i == total or i % 100 == 0 or total <= 20:
        print(f"[{i}/{total}] {name} -> {status}", file=sys.stderr, flush=True)


def cmd_run(args: argparse.Namespace) -> int:
    from .api import run_page3_pipeline

    cfg = _build_config(args)
    result = run_page3_pipeline(cfg, progress=None if args.quiet else _progress)
    print(result.summary())
    if result.counter_violations:
        print("\nfast-path counter violations:")
        for v in result.counter_violations[:20]:
            print(f"  {v}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    args.mode = "benchmark"
    return cmd_run(args)


def cmd_validate(args: argparse.Namespace) -> int:
    from .api import validate_run

    schema_root = Path(args.schema_root) if args.schema_root else None
    result = validate_run(Path(args.run_dir), schema_root)
    trimmed = dict(result)
    trimmed["results"] = [r for r in result["results"] if r["status"] != "PASS"]
    print(json.dumps(trimmed, indent=2, ensure_ascii=False))
    print(f"\n{result['pass_count']} PASS / {result['fail_count']} FAIL "
          f"over {result['schemas_checked']} schemas")
    return int(result["exit_code"])


def cmd_review(args: argparse.Namespace) -> int:
    from .api import review_run

    print(json.dumps(review_run(Path(args.run_dir)), indent=2, ensure_ascii=False))
    return 0


def cmd_findings(args: argparse.Namespace) -> int:
    from .api import generate_findings

    out = generate_findings(Path(args.run_dir),
                            Path(args.output_dir) if args.output_dir else None)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="page3_extractor",
        description=f"Page 3 extractor {EXTRACTOR_VERSION} "
                    f"(release status: {RELEASE_STATUS})",
    )
    p.add_argument("--version", action="version", version=EXTRACTOR_VERSION)
    p.add_argument("--quiet", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="execute an extraction run")
    _add_config_args(r)
    r.set_defaults(func=cmd_run)

    b = sub.add_parser("benchmark", help="run the deterministic stratified benchmark")
    _add_config_args(b)
    b.set_defaults(func=cmd_benchmark)

    v = sub.add_parser("validate", help="validate a run against the output contracts")
    v.add_argument("--run-dir", required=True)
    v.add_argument("--schema-root", default=None)
    v.set_defaults(func=cmd_validate)

    rv = sub.add_parser("review", help="summarise an existing run without re-running")
    rv.add_argument("--run-dir", required=True)
    rv.set_defaults(func=cmd_review)

    f = sub.add_parser("findings", help="generate producer findings from a frozen run")
    f.add_argument("--run-dir", required=True)
    f.add_argument("--output-dir", default=None)
    f.set_defaults(func=cmd_findings)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
