from __future__ import annotations


def validate_without_value_generation(
    computed_sum: float | None,
    published_total: float | None,
) -> dict[str, float | None]:
    """Return comparison evidence only; never derive or fill a source cell."""
    if computed_sum is None or published_total is None:
        return {"computed_sum": computed_sum, "published_total": published_total, "signed_delta": None}
    return {
        "computed_sum": computed_sum,
        "published_total": published_total,
        "signed_delta": computed_sum - published_total,
    }
