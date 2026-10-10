# Shipped registries

Editable reference data the extractor loads at runtime. Point `registry_root` at
a copy of this directory to override any of them without touching code.

## `p3_t2_roster_registry.csv`

The versioned dam-roster registry used to match T2 row labels to canonical dam
ids. If the file is absent the package falls back to the seed registry compiled
into `page3_extractor.roster`.

| column | meaning |
|---|---|
| `roster_version` | version of the registry as a whole |
| `dam_id` | canonical id assigned by this project |
| `name_ar` | the printed Arabic name |
| `name_en` | a readable English name; informational |
| `aliases` | pipe-separated spellings observed in the source |
| `valid_from`, `valid_to` | validity period — **empty means not measured, not "always"** |
| `evidence` | where the entry came from, and any caveat |

Two entries carry an explicit caveat: **Bouhertma** and **Zayatin** match the
reference dataset's names as *spelling variants*, not exact strings. They are
recorded as candidates and must not be promoted to a confirmed crosswalk without
a human decision.

### How matching works

Labels are normalized (NFKC, tatweel stripped, diacritics removed, alef and ya
folded) and compared first for equality, then for containment in either
direction — which is what lets `ملاق ( الى مستوى 265 م ) *` match `ملاق` without
loosening into fuzzy matching.

**No match is ever guessed.** An unmatched label is published as a
`dam_candidate` with a confidence and a `review_status`, never as a canonical
id. On a page whose text layer is control substitution no match is attempted at
all, and the row is published with `IDENTITY_UNRESOLVABLE_TEXT_REGIME`.

### Adding an entry

Add a row with a real `evidence` note saying where the spelling was observed.
Leave `valid_from` / `valid_to` empty unless you have measured them. Then rerun
and check `page3_t2_dam_status.csv` for rows whose `review_status` changed.
