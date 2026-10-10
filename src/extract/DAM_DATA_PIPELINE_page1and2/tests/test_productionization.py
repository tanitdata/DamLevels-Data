import hashlib
import json
from pathlib import Path

from dam_extraction.common.production_store import PRODUCTION_SCHEMA_SQL
from dam_extraction.common.serialization import DeterministicCSVWriter
from dam_extraction.page1.token_assembly import CharSpatialIndex, chars_in_bbox


def test_spatial_cache_preserves_exact_bbox_membership_and_order():
    chars = [
        {"text": "A", "x0": 1.0, "x1": 3.0, "top": 1.0, "bottom": 3.0},
        {"text": "B", "x0": 5.0, "x1": 7.0, "top": 8.0, "bottom": 10.0},
        {"text": "C", "x0": 2.0, "x1": 4.0, "top": 15.0, "bottom": 17.0},
        {"text": "D", "x0": 9.0, "x1": 11.0, "top": 7.9, "bottom": 8.1},
    ]
    index = CharSpatialIndex(chars, bin_height=8.0)
    for bbox in ([0, 0, 8, 12], [0, 7.99, 12, 16.1], [2, 2, 10, 9], [20, 20, 30, 30]):
        assert chars_in_bbox(index, list(bbox)) == chars_in_bbox(chars, list(bbox))


def test_streaming_gzip_bytes_are_deterministic():
    rows = [{"a": 1, "b": {"z": 2}}, {"a": 3, "b": [2, 1]}]
    temp_root = Path(__file__).resolve().parents[1] / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    paths = [temp_root / "determinism_a.csv.gz", temp_root / "determinism_b.csv.gz"]
    try:
        for path in paths:
            with DeterministicCSVWriter(path, ["a", "b"]) as writer:
                writer.writerows(rows)
        assert paths[0].read_bytes() == paths[1].read_bytes()
        assert hashlib.sha256(paths[0].read_bytes()).hexdigest() == hashlib.sha256(paths[1].read_bytes()).hexdigest()
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def test_production_database_declares_clean_room_classification():
    assert "development_or_production='PRODUCTION'" in PRODUCTION_SCHEMA_SQL
    assert "clean_room_classification='CLEAN_ROOM'" in PRODUCTION_SCHEMA_SQL
    assert "run_mode IN ('FULL','TARGETED')" in PRODUCTION_SCHEMA_SQL


def test_notebook_is_thin_executable_orchestration():
    notebook_path = Path(__file__).resolve().parents[1] / "page1" / "PAGE1_EXTRACTION.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])
    for name in ("RUN_MODE", "WORKERS", "INPUT_PDF_ROOT", "OUTPUT_ROOT", "WRITE_SQLITE", "WRITE_CSV"):
        assert name in source
    assert "execute_page1_run(" in source
    assert "pip install" not in source.casefold()
    assert "conda install" not in source.casefold()
    assert "def parse_numeric" not in source
    assert "def assemble_cell" not in source
