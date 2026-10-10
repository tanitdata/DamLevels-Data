from dam_extraction.common.sqlite_store import SCHEMA_SQL


def test_required_tables_are_declared():
    for table in (
        "run_manifest", "source_manifest", "page1_observation", "page1_value_lineage",
        "page1_checksum_source", "page1_checksum_validation", "page1_extraction_failure",
        "page1_unresolved_cell", "page1_validation_result",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA_SQL


def test_checksum_validation_contract_exposes_scope_and_counts():
    for field in (
        "execution_scope", "checksum_scope", "region_or_total",
        "expected_contributors", "observed_contributors", "numeric_contributors",
        "computed_sum", "published_sum", "signed_residual", "absolute_residual",
        "completeness", "tolerance_policy", "disposition",
    ):
        assert field in SCHEMA_SQL
