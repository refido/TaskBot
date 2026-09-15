"""Canonical row projections and the supported Reporter adapter contracts."""

from copy import deepcopy
from inspect import signature
from typing import Any
from unittest.mock import Mock

import pytest

from src import privacy
from src.infrastructure.reporting import row_queries
from src.infrastructure.reporting.models import TransactionRow
from src.privacy import nik_masking_enabled, set_nik_masking
from src.web.reporter import TransactionReporter

N1 = "1111111234222222"
N2 = "3333335678444444"
N3 = "1111119999222222"  # Same public value as N1 when masking is enabled.
QUERIES = (
    "get_mapping_error_report",
    "get_error_niks_by_reason",
    "get_error_niks_by_label",
    "get_mapping_failed_puzzle_report",
    "get_other_status_niks_by_status",
    "get_nik_parsing_failure_report",
)


@pytest.fixture(autouse=True)
def unmasked_history():
    previous = nik_masking_enabled()
    set_nik_masking(False)
    yield
    set_nik_masking(previous)


def reporter_for(rows):
    # These queries require only history, without starting the persistence lifecycle.
    reporter = object.__new__(TransactionReporter)
    reporter.rows = rows
    return reporter


@pytest.fixture
def query():
    return lambda name, rows: getattr(row_queries, name)(rows)


def mixed_rows():
    return [
        TransactionRow(N1, "completed"),
        TransactionRow(N2, "error", reason=" beta \nignored", error_label="Network"),
        TransactionRow(N1, "error", reason="alpha"),
        TransactionRow(N2, "error", reason="beta\nother", error_label="Network"),
        TransactionRow(N3, "error", reason="\nsecond"),
        TransactionRow(N1, "error", error_label=" "),
        TransactionRow(N1, "error", reason="Pelanggan Tidak Terdaftar"),
        TransactionRow(N2, "error", reason="NOT REGISTERED"),
        TransactionRow(N1, "failed_puzzle_solve"),
        TransactionRow(N2, "failed_puzzle_solve", reason="  "),
        TransactionRow(N1, "failed_puzzle_solve", reason=" full\ntrace "),
        TransactionRow(N1, "failed_puzzle_solve"),
        TransactionRow(N1, "skipped_quota"),
        TransactionRow(N2, "pending"),
        TransactionRow(N1, "custom"),
        TransactionRow(N2, "pending"),
        TransactionRow(N3, ""),
        TransactionRow(N1, "skipped_nik_parsing_failed", reason="bad region"),
        TransactionRow(N2, "skipped_nik_parsing_failed", reason="bad date"),
        TransactionRow(N1, "skipped_nik_parsing_failed", reason="bad region"),
        TransactionRow(N3, "skipped_nik_parsing_failed", reason="bad region"),
        TransactionRow(N2, "skipped_nik_parsing_failed"),
    ]


EXPECTED = {
    "get_mapping_error_report": {
        "beta": [N2, N2], "alpha": [N1], "unknown_error": [N3, N1],
    },
    "get_error_niks_by_reason": {
        "beta": [N2, N2], "alpha": [N1], "unknown_error": [N3, N1],
    },
    "get_error_niks_by_label": {
        "Network": [N2, N2], "application_level_error": [N1, N3], " ": [N1],
    },
    "get_mapping_failed_puzzle_report": {
        "CAPTCHA solving failed": [N1, N1], "": [N2], "full\ntrace": [N1],
    },
    "get_other_status_niks_by_status": {
        "pending": [N2, N2], "custom": [N1], "": [N3],
    },
    "get_nik_parsing_failure_report": {
        "total": 5,
        "by_reason": {
            "bad region": [N1, N3], "bad date": [N2], "Gagal parsing NIK": [N2],
        },
    },
}


def assert_ordered_equal(actual, expected):
    assert actual == expected
    if isinstance(expected, dict):
        assert list(actual) == list(expected)
        for key in expected:
            assert_ordered_equal(actual[key], expected[key])


@pytest.mark.parametrize("name", QUERIES)
def test_empty_history(query, name):
    expected = {"total": 0, "by_reason": {}} if name == QUERIES[-1] else {}
    assert_ordered_equal(query(name, []), expected)


@pytest.mark.parametrize("name", QUERIES)
def test_single_error_and_fallbacks(query, name):
    expected = {
        QUERIES[0]: {"unknown_error": [N1]},
        QUERIES[1]: {"unknown_error": [N1]},
        QUERIES[2]: {"application_level_error": [N1]},
        QUERIES[3]: {}, QUERIES[4]: {}, QUERIES[5]: {"total": 0, "by_reason": {}},
    }
    assert_ordered_equal(query(name, [TransactionRow(N1, "error")]), expected[name])


@pytest.mark.parametrize("name", QUERIES)
def test_mixed_history_order_duplicates_and_normalization(query, name):
    rows = mixed_rows()
    before = deepcopy(rows)
    assert_ordered_equal(query(name, rows), EXPECTED[name])
    assert rows == before


@pytest.mark.parametrize("name", QUERIES)
def test_fresh_containers_and_caller_mutation(query, name):
    rows = mixed_rows()
    before = deepcopy(rows)
    first, second = query(name, rows), query(name, rows)
    assert first is not second
    first_groups = first["by_reason"] if name == QUERIES[-1] else first
    second_groups = second["by_reason"] if name == QUERIES[-1] else second
    assert first_groups is not second_groups
    for key, values in first_groups.items():
        assert values is not second_groups[key]
        assert all(isinstance(value, str) for value in values)
        values.append("caller mutation")
    first_groups.clear()
    assert_ordered_equal(second, EXPECTED[name])
    assert_ordered_equal(query(name, rows), EXPECTED[name])
    assert rows == before


@pytest.mark.parametrize("name", QUERIES)
def test_privacy_is_projected_at_query_time(query, name):
    rows = mixed_rows()
    raw = query(name, rows)
    set_nik_masking(True)
    masked = query(name, rows)
    public = {N1: "111111****222222", N2: "333333****444444", N3: "111111****222222"}
    expected = deepcopy(EXPECTED[name])
    groups = expected["by_reason"] if name == QUERIES[-1] else expected
    for key, values in groups.items():
        projected = [public[value] for value in values]
        groups[key] = list(dict.fromkeys(projected)) if name == QUERIES[-1] else projected
    assert_ordered_equal(masked, expected)
    assert_ordered_equal(raw, EXPECTED[name])
    set_nik_masking(False)
    assert_ordered_equal(query(name, rows), raw)
    assert rows == mixed_rows()


def test_parsing_reason_sanitization_at_query_time(query, monkeypatch):
    # Config tests register credentials process-wide; own this test's registry.
    monkeypatch.setattr(privacy, "_private_values", {"query-secret"})
    reason = f"bad {N1} query-secret"
    rows = [TransactionRow(N1, "skipped_nik_parsing_failed", reason=reason)]
    assert query(QUERIES[-1], rows) == {
        "total": 1, "by_reason": {f"bad {N1} <redacted>": [N1]},
    }
    set_nik_masking(True)
    public = "111111****222222"
    assert query(QUERIES[-1], rows) == {
        "total": 1, "by_reason": {f"bad {public} <redacted>": [public]},
    }
    assert rows[0].reason == reason


@pytest.mark.parametrize("name", QUERIES)
def test_reporter_reads_current_history_after_replacement_and_mutation(name):
    reporter = reporter_for(mixed_rows())
    assert_ordered_equal(getattr(reporter, name)(), EXPECTED[name])
    set_nik_masking(True)
    masked = getattr(reporter, name)()
    assert_ordered_equal(masked, getattr(row_queries, name)(reporter.rows))
    assert masked != EXPECTED[name]
    set_nik_masking(False)
    assert_ordered_equal(getattr(reporter, name)(), EXPECTED[name])
    reporter.rows = []
    empty = {"total": 0, "by_reason": {}} if name == QUERIES[-1] else {}
    assert getattr(reporter, name)() == empty
    reporter.rows.extend(mixed_rows())
    assert_ordered_equal(getattr(reporter, name)(), EXPECTED[name])
    for row in reporter.rows:
        row.status = "completed"
    assert getattr(reporter, name)() == empty


@pytest.mark.parametrize("name", QUERIES)
def test_reporter_public_signature(name):
    method = signature(getattr(TransactionReporter, name))
    assert list(method.parameters) == ["self"]
    expected_return = dict[str, Any] if name == QUERIES[-1] else dict[str, list[str]]
    assert method.return_annotation == expected_return


@pytest.mark.parametrize("name", QUERIES)
def test_reporter_delegates_current_history_without_copying(name, monkeypatch):
    rows = mixed_rows()
    result = {"projection": []}
    projection = Mock(return_value=result)
    monkeypatch.setattr(row_queries, name, projection)
    assert getattr(reporter_for(rows), name)() is result
    projection.assert_called_once_with(rows)
    assert projection.call_args.args[0] is rows
    failure = RuntimeError("projection unavailable")
    projection.side_effect = failure
    with pytest.raises(RuntimeError) as raised:
        getattr(reporter_for(rows), name)()
    assert raised.value is failure


@pytest.mark.parametrize("name", QUERIES)
def test_query_preserves_input_exception(query, name):
    failure = RuntimeError("history unavailable")

    class UnreadableHistory:
        def __iter__(self):
            raise failure

    with pytest.raises(RuntimeError) as raised:
        query(name, UnreadableHistory())
    assert raised.value is failure
