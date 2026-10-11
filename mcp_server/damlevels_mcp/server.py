"""MCP server exposing the DamLevels-Data archive (read-only).

Run with ``python -m damlevels_mcp`` (stdio transport). The repository root is
found automatically, or set DAMLEVELS_DATA_ROOT.
"""
from __future__ import annotations

from functools import wraps
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .core import DamData, QueryError, default_root
from .ontology import Ontology

INSTRUCTIONS = """\
DamLevels-Data: daily storage of Tunisia's 36 large dams from the DGBGTH bulletins published by ONAGRI,
2 July 2014 to 10 October 2025. This is a historical archive: there is no data after 2025-10-10.

How to use the tools correctly:
- Find a dam's dam_id with find_dam or list_dams; dam names vary (French, Arabic, spellings).
- Storage is in Mm3 (million cubic metres) and describes the morning of the bulletin date.
- Inflow, release and daily transfer amounts printed on a bulletin describe the day BEFORE the bulletin;
  season-to-date amounts are totals from 1 September up to that day, not daily amounts.
- Never treat a missing day as zero and never fill gaps; report missing values as missing.
- Fill percentage depends on the capacity in force that day; use get_fill rather than dividing yourself.
- Page 3 transfer facts are PROBABLE; say so when you use them. Some Page 3 nodes map to a dam only as a
  candidate: get_transfers reports them separately; never treat them as confirmed.
- When describe_variable says a term is ambiguous, do not choose a meaning; ask with the printed column name.
- Errors come back as a result with an "error" field (e.g. BAD_DATE, OUTSIDE_RECORD); report them, do not guess.
- Quote the attribution returned with each result when you publish numbers. Use get_source to cite the
  exact bulletin page behind a storage value; transfer rows carry their own Page 3 source fields.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def build_server(root: Path | None = None) -> FastMCP:
    root = Path(root) if root else default_root()
    data = DamData(root)
    onto = Ontology(root)
    mcp = FastMCP("damlevels-data", instructions=INSTRUCTIONS)

    def tool(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except QueryError as err:
                return {**err.as_dict(), "coverage": data.coverage.as_dict()}
        return mcp.tool(annotations=READ_ONLY)(wrapper)

    @tool
    def dataset_info() -> dict:
        """What the archive contains: coverage dates, counts, units, time rules, source and licence."""
        return data.dataset_info()

    @tool
    def list_dams() -> dict:
        """All 36 dams with dam_id, French/Arabic names, coordinates, reference capacity and the period
        each dam appears in the bulletins."""
        return data.list_dams()

    @tool
    def find_dam(query: str) -> dict:
        """Find a dam's dam_id from a name in French or Arabic, an alias or a dam_id
        (e.g. 'Sidi Salem', 'سيدي سالم', 'S. EL BARRAK'). Returns match_type ('exact' or 'partial'),
        or candidates when the name is ambiguous or unknown."""
        return data.find_dam(query)

    @tool
    def get_storage(dam: str, start: str, end: str, resolution: str = "daily") -> dict:
        """Storage (Mm3) of one dam between two ISO dates (YYYY-MM-DD, inclusive).
        resolution='daily' returns each bulletin value (max 400 rows); 'monthly' returns
        first/last/min/max/mean per month. Missing bulletin dates are listed, never filled, and
        bulletins without a Page 1 are counted separately from days without any bulletin."""
        return data.get_storage(dam, start, end, resolution)

    @tool
    def get_fill(dam: str, date: str) -> dict:
        """Storage, capacity in force and fill percentage of one dam on one date, plus the fill
        percentage printed in the bulletin when there is one. No value is substituted for a missing day."""
        return data.get_fill(dam, date)

    @tool
    def national_storage(date: str) -> dict:
        """Total storage of all dams printed with a value on one date (YYYY-MM-DD), their combined fill
        over the dams whose capacity is known (numerator, denominator and excluded dams are given), and the
        national total printed in the bulletin with its rounding bound and any known disagreement."""
        return data.national_storage(date)

    @tool
    def compare_years(dam: str, month_day: str) -> dict:
        """Storage on the same calendar day (month_day='MM-DD') in every year of the record, for one dam
        or for 'all' dams. Useful for drought and year-on-year comparisons. Exact dates only;
        an impossible day such as '02-30' is refused with BAD_DATE."""
        return data.compare_years(dam, month_day)

    @tool
    def get_source(dam: str, date: str) -> dict:
        """Provenance of one storage value (Page 1): bulletin URL on ONAGRI, source file and SHA-256,
        page, printed column, cell position and the exact printed text. Not for transfers: each
        get_transfers row carries its own Page 3 source."""
        return data.get_source(dam, date)

    @tool
    def get_transfers(start: str, end: str, dam: str | None = None, measure: str = "today", limit: int = 200) -> dict:
        """Inter-dam transfer facts from bulletin Page 3 between two bulletin dates (YYYY-MM-DD, inclusive;
        authority PROBABLE). measure: 'today' (amount over the day before the bulletin),
        'current_season_to_date' or 'previous_season_to_date' (totals from 1 September up to that day).
        Optionally filter by a dam involved in the transfer; facts that reach this dam only through a
        candidate node crosswalk are returned separately. limit: 1 to 1000 rows (default 200). Each row
        carries both endpoint mapping statuses and its Page 3 source file, hash and evidence id."""
        return data.get_transfers(start, end, dam, measure, limit)

    @tool
    def describe_variable(term: str) -> dict:
        """Meaning of a bulletin term or printed column from the DamLevels ontology (DLO 0.3): concept,
        definition, unit, French/Arabic labels and the time rule of each printed column
        (e.g. 'Apports', 'الإيرادات', 'stored water volume', 'p1_release_today'). When a label belongs to
        several concepts, all candidates are returned with their printed columns and none is chosen."""
        return data._envelope(onto.describe(term))

    def doc(path: str):
        return lambda: (root / path).read_text(encoding="utf-8")

    for uri, path, title in [
        ("damlevels://docs/data-dictionary", "docs/data_dictionary.md", "Data dictionary"),
        ("damlevels://docs/known-issues", "docs/known_issues.md", "Known issues and source errors"),
        ("damlevels://docs/licence", "LICENSE-DATA", "Data licences and attribution"),
    ]:
        mcp.resource(uri, name=uri.rsplit("/", 1)[1], title=title, mime_type="text/markdown")(doc(path))

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
