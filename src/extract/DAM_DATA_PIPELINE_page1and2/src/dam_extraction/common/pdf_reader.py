from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pdfplumber


@contextmanager
def open_logical_page1(path: str | Path) -> Iterator[object]:
    source = Path(path)
    with pdfplumber.open(source) as document:
        if not document.pages:
            raise ValueError(f"PDF has no pages: {source}")
        page = document.pages[0]
        yield page

