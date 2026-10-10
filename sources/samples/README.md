# Sample bulletins

Two complete daily bulletins ("Situation des barrages") are included so users can see what the source documents look like. All other bulletins are not redistributed here; they are published by ONAGRI at <https://www.onagri.nat.tn/Situation-des-barrages/fr/19>, and `sources/manifest.csv` gives the `original_url` and per-page SHA-256 of every bulletin used.

| File | Bulletin date | Pages | SHA-256 | Why this one |
|---|---|---:|---|---|
| `2-7-2014.pdf` | 2014-07-02 | 3 | `b33ddbca6cd3aaf67514a32eff4e197d18a4f53a163620f26a430cb485b62ee8` | First bulletin in the record; early Page 1 layout without the fill-percentage column. |
| `01-02-2020.pdf` | 2020-02-01 | 3 | `409fd5458110b23962ca7364196f43cf1c6a4612d3f0377eeb99df3c7416bb69` | Later Page 1 layout with the fill-percentage column. |

Both files were downloaded again from their `original_url` on 2026-10-10 and are byte-identical to the copies used for extraction. The project splits each bulletin into pages (`<date>_1.pdf`, `_2.pdf`, `_3.pdf`); the page hashes in `sources/manifest.csv` refer to those split pages, not to these combined files.

`SAMPLE_SELECTION.csv` is the earlier E1 selection of single split pages; it records why each page was chosen and is kept as history.

**Source and licence.** Data producer: Direction Générale des Barrages et des Grands Travaux Hydrauliques (DGBGTH), Ministère de l'Agriculture, des Ressources Hydrauliques et de la Pêche. Publisher: Observatoire National de l'Agriculture (ONAGRI). Reused under the Licence Nationale de Données Publiques Ouvertes (see `LICENSE-DATA`).
