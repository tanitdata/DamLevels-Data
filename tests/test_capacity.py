from validate.capacity import capacity_for_date


def test_known_capacity():
    result = capacity_for_date("abid", "2015-03-19")
    assert result["status"] == "KNOWN"
    assert result["capacity_mm3"] == 9.62


def test_unresolved_transition_is_not_filled():
    result = capacity_for_date("brek", "2020-10-01")
    assert result["status"] == "UNAVAILABLE"
    assert result["capacity_mm3"] is None


def test_unknown_dam_is_unavailable():
    result = capacity_for_date("not-a-governed-id", "2020-01-01")
    assert result["status"] == "UNAVAILABLE"
