# E6A.2 multipage extraction and transcription audit

E6A.2 reports Page 1, Page 2 and Page 3 separately. It does **not** publish a pooled multipage accuracy. The production extractors were not invoked and accepted scientific values were not changed.

| Family | Primary PDFs | Eligible | Matches | Errors | Unverifiable | Wilson 95% CI | Decision |
|---|---:|---:|---:|---:|---:|---|---|
| A1_PAGE1_EXTRACTION | 800 | 800 | 800 | 0 | 0 | 99.522112%–100.000000% | YES |
| A2_PAGE2_EXTRACTION | 800 | 800 | 800 | 0 | 0 | 99.522112%–100.000000% | YES |
| A3_PAGE3_TRANSCRIPTION | 800 | 792 | 792 | 0 | 8 | 99.517309%–100.000000% | YES |

The Wilson bounds apply only within each independent-PDF family design. Page 3 remains `PROBABLE`; a transcription result does not establish semantic correctness or promote Page 3 authority.

## A1 Page 1 extraction

The primary estimand is one direct printed storage cell per sampled Page 1 PDF. Layout-15 and layout-16 bulletins are sampled proportionally.

## A2 Page 2 extraction

One direct numeric cell is selected per sampled Page 2 PDF. Field-family results remain descriptive; capacity, storage, inflow/outflow, evaporation, rainfall and previous-year semantics are not merged before their field labels are preserved.

## A3 Page 3 numeric transcription

The primary sample uses direct `today` or `current_season_to_date` numeric cells. Previous-season values appear only in the challenge/qualification layer. Source localization is inherited from Page 3 evidence IDs and cell boxes; the reread does not call the production parser functions.

## A3B Page 3 semantic mapping

Categorical dispositions: `{"ACCOUNTING_NOT_HYDRAULIC_EDGE": 39, "DATE_SEMANTICS_UNRESOLVED": 45, "PRINTED_LABEL_MATCH_STABLE_ID_UNRESOLVED": 76}`.

This review keeps physical routes separate from the Sejnane accounting observation, leaves candidate dam crosswalks unresolved and preserves the effective-date conflict. It is not combined with A3 transcription accuracy.

## Challenge set

The separate noninferential challenge set contains **28** rows. No challenge row enters an A1/A2/A3 Wilson denominator.

## Verification method

All primary cells are `COMPUTER_ASSISTED_SOURCE_REREAD` from original source PDF regions. Localization is inherited from preserved production lineage. No E6A.2 row is represented as a human manual verification.

## Completeness denominator clarification

The 143,316 Page 1 opportunities are 3,981 Page 1 bulletin dates × 36 governed dams. The 144 opportunities from four partial bulletins without Page 1 are labeled `OUTSIDE_DENOMINATOR_PARTIAL_BULLETIN_OPPORTUNITIES`; they are not added to that denominator.

Correction candidates: **0**.
