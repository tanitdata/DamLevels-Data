from __future__ import annotations

from .pdf_reader import SourcePage


def _page_score(page: SourcePage) -> tuple[int, int]:
    normalized = " ".join(str(word.get("text", "")).casefold() for word in page.words)
    score = 0
    score += 2 if "service)" in normalized else 0
    score += 2 if "barrages" in normalized else 0
    score += 1 if "total general" in normalized else 0
    score += 1 if len(page.rects) >= 100 else 0
    return score, -page.page_number


def select_logical_page2(pages: list[SourcePage]) -> SourcePage:
    selected = max(pages, key=_page_score)
    score, _ = _page_score(selected)
    if score < 4:
        raise ValueError("No deterministic logical Page-2 table page found")
    return selected
