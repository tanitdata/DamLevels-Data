# DamLevels Ontology (DLO) 0.3

A spreadsheet can hold the number `8,645`, but it cannot say what the number is. DLO is the vocabulary that says it: **what** was measured, **where**, **for which day**, in **which unit**, and **which bulletin page** it came from.

| Without the ontology | With the ontology |
|---|---|
| `8,645` in a column headed *Lâchers du jour* | **released water volume** · Sidi El Barrak reservoir · **31 January 2019** · million m³ · a reference value from one year earlier, not today's · bulletin of 1 February 2020, page 1 |

## Why it was needed

The bulletin headings do not always mean what they seem to say:

- Under *Lâchers du jour* (release of the day) two values are printed: the release over day D−1 and the release on the **same day one year earlier**. The second one is extracted as `p1_release_today`, a name that suggests the opposite; the current release is `p1_release_yesterday`.
- Flows printed on the bulletin of day D (inflow, release, transfer, evaporation) describe **day D−1**. Stocks, levels and fill describe **day D**. You can see this on the page itself: *"du 31-01-20 observée le 01-02-20"*.
- Month-to-date totals run from the first day of the month of D−1, and season totals from 1 September, so they restart on the bulletin of the 2nd of the month and of 2 September.
- The same idea appears under different headings on different pages (*Apports*, *الإيرادات*, *Volume correspondant*…).

DLO writes each of these rules once and applies it to every value.

## What is in it

| Part | Count | Example |
|---|---:|---|
| Printed columns mapped (`dlo:ColumnMapping`) | 84 | `p1_stock_today_mm3` → stored water volume, state at the bulletin date |
| Concepts (variables) | 33 | stored water volume, inflow volume, released water volume, evaporated volume… |
| Time rules (`dlc:TemporalSupportScheme`) | 16 | state at the bulletin date · amount over the day before the bulletin · running total since 1 September · state on the same date one year earlier |
| Dams, reservoirs, catchments | 36 each | the dam (the wall), its reservoir (the water) and its catchment (the land) are separate things |
| Semantic tests (`dlo:SemanticTest`) | 46 | checks run on the whole archive that support each mapping |
| Sample observations | 200 | real values from the bulletins, each linked to its page by SHA-256 |

The Page 2 column "R.S." is mapped but has no concept: the publisher does not document what it means, so DLO does not guess.

DLO reuses W3C and OGC standards rather than inventing terms: SOSA (observations), OWL-Time (days and intervals), QUDT (units), PROV (provenance), SKOS (code lists), I-ADOPT (variable decomposition), HY_Features (water bodies and catchments) and DQV (quality measurements).

## Files

| File | Use |
|---|---|
| `DLO_0.3_VIEW_20260929-2345.ttl` | Turtle: schema, code lists, dams/reservoirs/catchments and 200 sample observations in one file (8,083 triples) |
| `DLO_0.3_VIEW_20260929-2345.owl` | The same content as RDF/XML, for Protégé |
| `queries/*.rq` | Example SPARQL queries (below) |
| `../qa/kpi/ontology_ref/` | The variable catalogue, the time rules as Python, and the 46 semantic tests used by the quality checks |

This file is a **view**: it merges the ontology modules and a sample of observations so it can be opened and queried directly. The full instance graph built during the project (about 3.2 million observations) is not included in this repository. Version 0.3.0 is a research build; the `https://w3id.org/damlevels/` namespace is not yet registered with w3id.org.

## Try it

Open the `.owl` file in [Protégé](https://protege.stanford.edu/), or query the `.ttl` file in Python:

```bash
pip install rdflib
```

```python
import rdflib
g = rdflib.Graph()
g.parse("ontology/DLO_0.3_VIEW_20260929-2345.ttl", format="turtle")
for row in g.query(open("ontology/queries/observations_for_one_dam.rq").read()):
    print(row.variable, row.value, row.describes, "|", row.timeRule)
```

Output (Sidi El Barrak, bulletin of 1 February 2020 and a later sample):

```
inflow volume           0.016    2020-01-31/P1D  | amount over the day before the bulletin
released water volume   0.0      2020-01-31/P1D  | amount over the day before the bulletin
stored water volume     280.478  2019-02-01      | state on the same date one year earlier
stored water volume     283.496  2020-02-01      | state at the bulletin date
stored water volume     103.195  2024-08-28      | state at the bulletin date
```

The same three numbers sit side by side in one printed row; the ontology gives each its own day.

| Query | Question it answers |
|---|---|
| `observations_for_one_dam.rq` | What was measured at one dam, for which day, under which time rule, from which page? |
| `column_meanings.rq` | What does each printed column mean, and how is it dated? (83 rows) |
| `time_rules.rq` | Which time rules exist, and how many columns use each? (16 rows) |

## Tests

`tests/test_ontology.py` (run with `pytest`) checks that:

- the Turtle and OWL files carry the same statements;
- the counts above are correct (84 mappings, 33 concepts, 16 time rules, 46 semantic tests, 200 observations, 36 dams/reservoirs/catchments);
- every observation has its feature, concept, time, column mapping and source page, and every empty one carries an explicit status (for example *not printed in this layout*);
- every concept and time rule has a label and a definition, and no undefined project term is referenced;
- the 20 sample storage observations equal the values in `data/storage.csv`;
- the example queries return the documented rows, and inflow is dated the day before the bulletin;
- OWL RL reasoning (owlrl) finds no contradiction.

Not covered here: the full instance graph and its SHACL rules, which are not part of this repository.

## Licence

CC BY 4.0, like the other project material (see `../LICENSE-DATA`). The sample observation values come from the DGBGTH bulletins published by ONAGRI; keep the source attribution.
