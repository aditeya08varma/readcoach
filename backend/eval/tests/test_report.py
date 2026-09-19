"""Unit tests for `report.py`'s pure statistics helpers - `percentile()` and
`mean_range()`. No API calls, no fixtures beyond plain lists of numbers; per
an audit finding that the eval harness had zero unit test coverage of its
own logic despite being a pure-Python, easily-testable module.
"""

import math

from report import mean_range, percentile


def test_percentile_of_empty_list_is_none():
    """A stage with zero real samples should show up as `null` in the
    report rather than crashing the whole benchmark run.
    """
    assert percentile([], 50) is None
    assert percentile([], 95) is None


def test_percentile_of_single_value_is_that_value():
    assert percentile([42.0], 50) == 42.0
    assert percentile([42.0], 95) == 42.0


def test_percentile_median_of_odd_length_list():
    # Odd-length list: P50 lands exactly on the middle element, no
    # interpolation needed.
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0


def test_percentile_p0_and_p100_are_min_and_max():
    values = [5.0, 1.0, 4.0, 2.0, 3.0]
    assert percentile(values, 0) == 1.0
    assert percentile(values, 100) == 5.0


def test_percentile_matches_numpy_linear_interpolation_convention():
    # percentile()'s own docstring claims "same convention as numpy's
    # default" - verify against a hand-computed interpolated case instead
    # of trusting the claim: rank = 0.95 * (5 - 1) = 3.8, so P95 sits 80%
    # of the way between the 4th (index 3, value 4) and 5th (index 4,
    # value 5) sorted elements: 4 + 0.8 * (5 - 4) = 4.8.
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 95) == 4.8


def test_percentile_sorts_unsorted_input():
    # Deliberately fed out of order - percentile() must sort internally
    # rather than assuming a pre-sorted list.
    assert percentile([30.0, 10.0, 20.0], 50) == 20.0


def test_percentile_rounds_to_one_decimal_place():
    result = percentile([1.0, 2.0], 25)
    assert result == round(result, 1)


def test_percentile_handles_a_realistic_latency_sample():
    # A shape resembling this harness's own hint-generation latencies
    # (mostly fast, one real slow outlier) - P50 should sit near the bulk,
    # P95 should be pulled toward the outlier.
    latencies_ms = [900.0, 950.0, 1000.0, 1050.0, 1100.0, 1080.0, 990.0, 970.0, 1010.0, 11627.0]
    p50 = percentile(latencies_ms, 50)
    p95 = percentile(latencies_ms, 95)
    assert 950.0 <= p50 <= 1050.0
    assert p95 > p50
    assert p95 > 5000.0  # the one slow outlier should dominate P95, not P50


def test_mean_range_of_empty_list_is_none():
    assert mean_range([]) is None


def test_mean_range_drops_none_entries_before_aggregating():
    # A trial with zero checkable samples reports None for that trial - it
    # should be excluded from the mean/range, not treated as 0.
    stat = mean_range([0.8, None, 0.9, None])
    assert stat is not None
    assert stat["n_trials"] == 2
    assert stat["mean"] == 0.85
    assert stat["min"] == 0.8
    assert stat["max"] == 0.9


def test_mean_range_all_none_is_none():
    assert mean_range([None, None]) is None


def test_mean_range_reports_the_exact_audit_finding_numbers():
    # The concrete numbers from this fix's own motivating audit: identical
    # code and sample, three runs, skill_tagging_accuracy read 66.7%,
    # 73.3%, and 100%.
    stat = mean_range([0.667, 0.733, 1.0])
    assert stat["n_trials"] == 3
    assert stat["min"] == 0.667
    assert stat["max"] == 1.0
    assert math.isclose(stat["mean"], (0.667 + 0.733 + 1.0) / 3, rel_tol=1e-6)


def test_mean_range_single_value_has_zero_spread():
    stat = mean_range([0.9])
    assert stat["mean"] == stat["min"] == stat["max"] == 0.9
    assert stat["n_trials"] == 1


def test_mean_range_preserves_each_trial_value():
    stat = mean_range([1.0, 2.0, 3.0])
    assert stat["values"] == [1.0, 2.0, 3.0]
