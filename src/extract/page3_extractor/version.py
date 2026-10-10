"""Version constants.

Every generated evidence row carries ``extractor_version``. The routing and
semantics versions are separate so that a pure-performance change (which must
reproduce identical output hashes) can be told apart from a change that alters
what a value *means*.

One spelling, everywhere. ``EXTRACTOR_VERSION`` is a valid PEP 440 release
identifier, so ``pyproject.toml``, the built wheel's filename and metadata, the
CLI's ``--version``, the run manifest and the README all carry the *same*
string. ``tests/unit/test_packaging_version.py`` asserts that equality; the
Phase 5B audit found the 1.1.0 candidate declaring three different versions
across those five places.
"""

EXTRACTOR_VERSION = "1.2.0rc2"
"""Version of the extraction code as a whole. Part of the cache key.

1.2.0rc2 is the Phase 6C R1 T2 overprint recovery, PATCH-P5D-001. It changes
exactly one thing: a T2 value cell on an ``R1_c0_control_substitution`` page
that the strict-unanimity rule refused *because its draws disagreed* is re-read
once from the page's own glyph trace, where no decoder configuration removes a
coincident glyph, and publishes only if every complete printed draw there parses
to the identical value. Unanimity is not weakened; it is given the draws the
page actually makes. No other family, page, gate or value is touched, and no R1
dam identity is inferred.

1.2.0rc1 was the Phase 5C targeted completeness patch: the conditional
native-span fallback on the page context's existing TextPage, R2 T5 daily
recovery, R2 T2 numeric recovery at row-slot grain, R2 T2 identity from exact
normalised span labels, strict-unanimity adjudication of R1 overprint draws,
source-ruled T6 evidence boxes, published per-family usability, and a generic
orphan-numeric silent-omission detector. 1.0.0, 1.1.0-candidate and 1.2.0rc1 are
immutable and stay on disk at ``04_extractors/production``,
``04_extractors/production_v1_1`` and ``04_extractors/production_v1_2``.
"""

ROUTING_VERSION = "1.0.0"
"""Version of the logical-page classification and route table. Unchanged by the
Phase 5A and 5C repairs: no routing decision, fragment assignment or shape rule
moved."""

SEMANTICS_VERSION = "1.2.1"
"""Version of the T1-T6 canonical field maps and schema-era rules.

1.2.0 was raised because Phase 5C added published columns
(``dam_candidate_raw``, ``dam_candidate_normalized``, ``identity_status``,
``family_usability_status``) and two recovery methods
(``RAWDICT_SPAN_FALLBACK``, ``OVERPRINT_UNANIMOUS``).

1.2.1 adds one further recovery method, ``OVERPRINT_GLYPH_TRACE_UNANIMOUS``,
and no field. Every field identity, unit, temporal reference, semantic state and
identity status means exactly what it meant in 1.2.0; the only change is that
7,213 R1 T2 cells move from ``unparseable_numeric_candidate`` to ``numeric``
because the reader stopped destroying one of the two draws it was adjudicating.
Dam identity for those rows is unchanged and still unresolved."""

SCHEMA_CONTRACT_VERSION = "1.3.0"
"""Version of the output-table contract (Phase 2 27 tables + Phase 3 additions +
the Phase 5A and Phase 5C additive fact columns).

Unchanged by 1.2.0rc2: PATCH-P5D-001 adds no table, no column and no controlled
value outside ``recovery_method``."""

PRODUCT_NAME = "page3_extractor"

RELEASE_STATUS = "AUDITED_ACCEPTED_WITH_LIMITATIONS"
"""Phase 6C. The Phase 5D independent re-audit verified the 1.2.0rc1 code and
its run and raised PATCH-P5D-001; 1.2.0rc2 implements exactly that patch, and
the Phase 6C bounded independent re-audit re-read all 7,213 recovered cells from
the source's own draw evidence with an audit-only reader that does not import
this package's recovery modules.

Accepted **with limitations**, which are not optional reading:

* R1 T2 numeric values are recoverable and recovered; R1 **dam identity**
  remains unresolved (``IDENTITY_UNRESOLVABLE_TEXT_REGIME``) and no positional
  assignment is permitted.
* the DAM-EL-HMA roster mapping is provisional.
* dam-to-region membership is not established by this source.
* some source arithmetic and cumulative corrections remain source-authentic
  flags, not repairs: the extractor publishes what the bulletin prints."""
