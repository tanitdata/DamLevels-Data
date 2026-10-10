from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pdfplumber


@dataclass(frozen=True)
class SourcePage:
    page_number: int
    width: float
    height: float
    words: list[dict]
    rects: list[dict]


@dataclass(frozen=True)
class SourcePdf:
    path: Path
    sha256: str
    pages: list[SourcePage]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_source_pdf(path: str | Path) -> SourcePdf:
    source_path = Path(path)
    source_hash = sha256_file(source_path)
    pages: list[SourcePage] = []
    with pdfplumber.open(source_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(
                x_tolerance=1.5,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            pages.append(
                SourcePage(
                    page_number=page_number,
                    width=float(page.width),
                    height=float(page.height),
                    words=[dict(word) for word in words],
                    rects=[dict(rect) for rect in page.rects],
                )
            )
    if not pages:
        raise ValueError(f"PDF contains no pages: {source_path.name}")
    return SourcePdf(source_path, source_hash, pages)
