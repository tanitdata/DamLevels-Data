# DamLevels MCP server

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server that lets an AI assistant (Claude Desktop, Claude Code, or any MCP client) answer questions about Tunisia's dams from the DamLevels-Data archive — with the correct dating rules and a citation to the exact bulletin page behind every number.

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
| `find_dam(query)` | `dam_id` from a French or Arabic name, alias or spelling variant; candidates if ambiguous |
| `get_storage(dam, start, end, resolution)` | daily values (max 400) or monthly summaries; missing bulletin dates listed, never filled |
| `get_fill(dam, date)` | storage, capacity in force that day, fill %, and the fill % printed in the bulletin |
| `national_storage(date)` | total of all dams printed that day, combined fill, and the printed national total |
| `compare_years(dam, month_day)` | the same calendar day in every year, for one dam or `all` |
| `get_source(dam, date)` | bulletin URL, source file and SHA-256, page, column, cell position, printed text |
| `get_transfers(start, end, dam, measure)` | Page 3 inter-dam transfers (authority `PROBABLE`) |
| `describe_variable(term)` | meaning, unit, labels and time rule of a term or printed column, from the DLO ontology |

Resources: `damlevels://docs/data-dictionary`, `damlevels://docs/known-issues`, `damlevels://docs/licence`.

Every answer carries the record's coverage, the source attribution and any caveats (for example *"Page 3 facts are PROBABLE"* or *"capacity UNAVAILABLE; fill not computed"*).

## Rules built into the server

- Storage describes the morning of the bulletin date; inflow, release and transfer amounts describe the day **before** the bulletin.
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

`tests/test_mcp_server.py` (run with `python -m pytest -q` from the repository root) checks every tool against the published tables, the no-fill and out-of-record rules, the ontology lookups, and the MCP protocol itself.

## Licence

Code: MIT. Data returned by the server: see `LICENSE-DATA` — source values under the Licence Nationale de Données Publiques Ouvertes (cite DGBGTH/ONAGRI), project tables CC BY 4.0.
