# DamLevels MCP server

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server that lets an AI assistant (Claude Desktop, Claude Code, or any MCP client) answer questions about Tunisia's dams from the DamLevels-Data archive — with the correct dating rules and a citation to the bulletin page behind every number (`get_source` for storage values; each transfer row carries its own Page 3 source).

> **Coverage: 2 July 2014 – 10 October 2025.** This is a historical archive. Questions about later dates are answered with `OUTSIDE_RECORD`; no value is ever estimated.

## What you can ask

- *"How full was Sidi Salem on 1 October each year since 2015?"*
- *"Total storage of Tunisian dams on 10 October 2025, and how does it compare with 2018?"*
- *"Where does the value 283.496 for Sidi El Barrak on 1 February 2020 come from?"*
- *"What does* الإيرادات *mean in the bulletin, and which day does it refer to?"*

## Tools

| Tool | What it returns |
|---|---|
| `dataset_info` | coverage, counts, units, time rules, source, licence |
| `list_dams` | 36 dams: `dam_id`, French/Arabic names, coordinates, reference capacity, period in the bulletins |
| `find_dam(query)` | `dam_id` from a French or Arabic name, alias or spelling variant, with `match_type` (`exact` or `partial`); candidates if ambiguous or unknown |
| `get_storage(dam, start, end, resolution)` | daily values (max 400) or monthly summaries; missing bulletin dates listed, never filled; bulletins without a Page 1 counted apart from days without any bulletin |
| `get_fill(dam, date)` | storage, capacity in force that day, fill %, and the fill % printed in the bulletin |
| `national_storage(date)` | total of all dams printed that day; combined fill over the dams with known capacity (numerator, denominator and excluded dams given); the printed national total with its rounding bound and any known disagreement |
| `compare_years(dam, month_day)` | the same calendar day in every year, for one dam or `all`; `02-29` gives the leap years only |
| `get_source(dam, date)` | for a **storage** value: bulletin URL, Page 1 source file and SHA-256, column, cell position, printed text |
| `get_transfers(start, end, dam, measure, limit)` | Page 3 inter-dam transfers (authority `PROBABLE`) between two **bulletin** dates; each row has its fact id, both endpoint mapping statuses, and its Page 3 file, SHA-256, evidence id and printed text; rows that reach a dam only through a candidate crosswalk (Bouhertma→Bou Heurtma, Zayatin→Ziatine) are listed separately, never promoted; `limit` 1–1000 |
| `describe_variable(term)` | meaning, unit, labels and time rule of a term or printed column, from the DLO ontology; when a label belongs to several concepts (e.g. الفارق) all candidates are returned and none is chosen |

Resources: `damlevels://docs/data-dictionary`, `damlevels://docs/known-issues`, `damlevels://docs/licence`.

Every answer carries the record's coverage, the source attribution and any caveats (for example *"Page 3 facts are PROBABLE"* or *"capacity UNAVAILABLE; fill not computed"*).

## Rules built into the server

- Storage describes the morning of the bulletin date; inflow, release and daily transfer amounts describe the day **before** the bulletin.
- Transfers: `start`/`end` and `bulletin_date` are bulletin dates. The published table stores `date` = bulletin date with `effective_date_rule = SAME_DAY`; under the ontology (DLO 0.3) the `today` amount is for day D−1 and the season-to-date amounts are totals from 1 September up to day D−1, not daily amounts. Each answer states the time rule of the measure asked for.
- Invalid input is refused with an error code instead of an empty answer: `BAD_DATE` (only `YYYY-MM-DD`; `MM-DD` must be a real calendar day), `BAD_RANGE` (start after end), `BAD_LIMIT`, `OUTSIDE_RECORD`, `UNKNOWN_DAM` / `AMBIGUOUS_DAM`, `ONTOLOGY_UNAVAILABLE` (rdflib not installed). Errors come back as a normal result with an `error` field.
- A missing day is reported as missing — never zero, never interpolated, never replaced by the nearest value.
- Fill uses the capacity regime in force on that date; it is not computed when that capacity is unknown or ambiguous.
- Dams are matched by `dam_id`; names are only used to find it.

## Install and run

From a clone of the repository:

```bash
pip install -e "mcp_server[ontology]"      # mcp, pandas, pyarrow, pydantic (+ rdflib for describe_variable)
python -m damlevels_mcp                     # stdio server; or the `damlevels-mcp` command
```

The server reads the tables of the repository it lives in. To point it at another copy, set `DAMLEVELS_DATA_ROOT` to that repository's root.

**Claude Code**

```bash
claude mcp add damlevels -- damlevels-mcp
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "damlevels": { "command": "damlevels-mcp" }
  }
}
```

If `damlevels-mcp` is not on your PATH (pip prints a warning when its scripts folder is not, e.g. `%APPDATA%\Python\Python3xx\Scripts` on Windows), give the full path to that executable, or use your Python with the module:

```json
{
  "mcpServers": {
    "damlevels": { "command": "python", "args": ["-m", "damlevels_mcp"] }
  }
}
```

## Tests

`tests/test_mcp_server.py` (run with `python -m pytest -q` from the repository root) covers:

- values against the published CSV tables: daily storage, monthly means (exact decimal mean, rounded half-to-even to 0.001 Mm³), fill and printed fill, national totals and leap-day totals, source cells, and transfer amounts, mapping statuses and source fields;
- the rules: no filling of missing days, partial bulletins without Page 1, out-of-record dates, invalid dates, ranges and limits, the national-fill subset and the known national disagreements, candidate transfer endpoints, dam name variants (including Arabic tatweel), ambiguous ontology labels and a missing rdflib;
- the MCP layer: tool and resource listing in-process, and real stdio sessions (the server started as a subprocess with `python -m damlevels_mcp`), including the ambiguous Arabic labels under three different hash seeds.

The tests do not check every date of the record or every tool argument combination.

## Licence

Code: MIT. Data returned by the server: see `LICENSE-DATA` — source values under the Licence Nationale de Données Publiques Ouvertes (cite DGBGTH/ONAGRI), project tables CC BY 4.0.
