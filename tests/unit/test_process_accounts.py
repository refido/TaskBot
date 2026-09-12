"""Controlled account scheduling; no wall-clock sleeps or real browsers."""

from collections import Counter
from functools import partial
from queue import Queue
from threading import Event, Lock, Thread, get_ident
from types import SimpleNamespace
from unittest.mock import Mock
import importlib

import pytest

import main as taskbot_main

use_case = importlib.import_module("src.application.use_cases.process_account")


def controlled_accounts(count, *, limit=None, failure=None, release_order=None):
    configs = [SimpleNamespace(operator_id=f"operator_{i}") for i in range(count)]
    gates = [Event() for _ in configs]
    started, finished = Queue(), Queue()
    lock = Lock()
    active = peak = 0
    calls, dependencies = [], []
    shared_limiter = object()
    outcomes = {config.operator_id: {} for config in configs}
    log = Mock()

    def bind(**fields):
        if fields.get("event") in {"account.thread.finished", "account.thread.crashed"}:
            finished.put(fields)
        return Mock()

    log.bind.side_effect = bind

    def run(config, *, update_limiter):
        nonlocal active, peak
        index = configs.index(config)
        with lock:
            calls.append(index)
            dependencies.append(update_limiter)
            active += 1
            peak = max(peak, active)
        started.put(index)
        try:
            assert gates[index].wait(10), "controller did not release worker"
            if failure == (index, "exception"):
                raise RuntimeError("worker exploded")
            successful = failure != (index, "account")
            outcomes[config.operator_id]["status"] = "completed" if successful else "failed"
            return config.operator_id, successful
        finally:
            with lock:
                active -= 1

    result = {}

    def drive():
        try:
            kwargs = {} if limit is None else {"max_concurrent_accounts": limit}
            result["rows"] = use_case.process_accounts(
                configs, run_account=partial(run, update_limiter=shared_limiter),
                log=log, outcomes=outcomes, **kwargs,
            )
        except BaseException as exc:
            result["exception"] = exc

    controller = Thread(target=drive, daemon=True)
    controller.start()
    effective = min(count, limit or count)
    completion_order = []
    try:
        running = {started.get(timeout=10) for _ in range(effective)}
        for position in range(count):
            index = release_order[position] if release_order else min(running)
            assert index in running
            running.remove(index)
            gates[index].set()
            event = finished.get(timeout=10)
            assert event["operator_id"] == configs[index].operator_id
            completion_order.append(event)
            if position + effective < count:
                running.add(started.get(timeout=10))
    finally:
        for gate in gates:
            gate.set()
        controller.join(timeout=10)
    assert not controller.is_alive()
    assert "exception" not in result, result.get("exception")
    assert active == 0
    assert Counter(calls) == Counter(range(count))
    assert all(value is shared_limiter for value in dependencies)
    return SimpleNamespace(
        peak=peak, results=result["rows"], completion_order=completion_order,
        configs=configs, outcomes=outcomes, log=log,
    )


@pytest.mark.parametrize("limit", [None, 1, 10])
def test_zero_accounts_does_not_create_executor(monkeypatch, limit):
    executor, run = Mock(), Mock()
    monkeypatch.setattr(use_case, "ThreadPoolExecutor", executor)
    assert use_case.process_accounts(
        [], run_account=run, log=Mock(), max_concurrent_accounts=limit
    ) == []
    executor.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("successful", [True, False])
@pytest.mark.parametrize("limit", [None, 1, 10])
def test_one_account_runs_on_calling_thread(monkeypatch, successful, limit):
    config, caller = object(), get_ident()
    executor = Mock()
    monkeypatch.setattr(use_case, "ThreadPoolExecutor", executor)

    def run(value):
        assert value is config
        assert get_ident() == caller
        return "operator_0", successful

    assert use_case.process_accounts(
        [config], run_account=run, log=Mock(), max_concurrent_accounts=limit
    ) == [
        ("operator_0", successful)
    ]
    executor.assert_not_called()


@pytest.mark.parametrize("limit", [None, 1])
def test_single_worker_exception_propagates(limit):
    failure = RuntimeError("single account failed")
    with pytest.raises(RuntimeError) as caught:
        use_case.process_accounts(
            [object()], run_account=Mock(side_effect=failure), log=Mock(),
            max_concurrent_accounts=limit,
        )
    assert caught.value is failure


@pytest.mark.parametrize("count", [2, 5])
def test_legacy_default_can_start_every_account_together(count):
    # Measured against the old implementation before adding a configurable cap.
    case = controlled_accounts(count)
    assert case.peak == count
    assert case.results == [(f"operator_{i}", True) for i in range(count)]


@pytest.mark.parametrize("limit", [None, 4, 10])
def test_return_order_follows_observed_completion_not_input(limit):
    order = [3, 1, 2, 0]
    case = controlled_accounts(4, limit=limit, release_order=order)
    assert case.results == [(f"operator_{i}", True) for i in order]


@pytest.mark.parametrize("failure", ["account", "exception"])
@pytest.mark.parametrize("limit", [None, 1, 2])
def test_failure_does_not_cancel_other_accounts(failure, limit):
    case = controlled_accounts(4, limit=limit, failure=(1, failure))
    expected = [(f"operator_{i}", i != 1) for i in range(4)]
    if failure == "exception":
        expected.pop(1)  # Existing contract: crash logged, tuple omitted.
        assert case.completion_order[1]["event"] == "account.thread.crashed"
    assert case.results == expected
    assert taskbot_main._aggregate_run_status(case.configs, case.results, case.outcomes) == "failed"


@pytest.mark.parametrize("limit", [None, 1, 2])
def test_main_shares_one_limiter_through_every_account_runner(monkeypatch, limit):
    limiter = object()
    seen = []
    lock = Lock()

    class Runner:
        def __init__(self, *, limiter_factory, **kwargs):
            self.limiter = limiter_factory()

        def run(self, config):
            with lock:
                seen.append((config, self.limiter))
            return config.operator_id, True

    monkeypatch.setattr(taskbot_main, "AccountRunner", Runner)
    monkeypatch.setattr(taskbot_main, "DatabaseReportSyncer", Mock())
    # Inspect the actual main.run_account -> AccountRunner limiter factory.
    monkeypatch.setattr(taskbot_main, "SkipRateLimiter", lambda **kw: kw["customer_update_rate_limiter"])
    configs = [SimpleNamespace(operator_id=f"operator_{i}") for i in range(4)]
    results = use_case.process_accounts(
        configs, run_account=partial(taskbot_main.run_account, update_limiter=limiter), log=Mock(),
        max_concurrent_accounts=limit,
    )
    assert len(results) == len(seen) == len(configs)
    assert all(value is limiter for _, value in seen)
    assert {id(config) for config, _ in seen} == {id(config) for config in configs}


@pytest.mark.parametrize("count,limit", [(2, 5), (3, 3), (5, 2), (5, 1), (5, 100)])
def test_explicit_limit_bounds_peak_and_runs_every_account(count, limit):
    case = controlled_accounts(count, limit=limit)
    assert case.peak == min(count, limit)
    assert len(case.results) == count
    startup = next(call.kwargs for call in case.log.bind.call_args_list
                   if call.kwargs.get("event") == "app.concurrent_start")
    assert startup["max_workers"] == min(count, limit)
    assert startup["max_concurrent_accounts"] == limit
    assert taskbot_main._aggregate_run_status(case.configs, case.results, case.outcomes) == "completed"


def test_bounded_workers_preserve_out_of_order_completion():
    # Hold worker 0 while workers 1 -> 2 -> 3 successively occupy the second slot.
    case = controlled_accounts(4, limit=2, release_order=[1, 2, 3, 0])
    assert case.peak == 2
    assert case.results == [(f"operator_{i}", True) for i in [1, 2, 3, 0]]


@pytest.mark.parametrize("limit", [0, -1, "2", "broken", 1.5, True, False])
@pytest.mark.parametrize("count", [0, 1, 3])
def test_invalid_limit_rejected_before_starting_accounts(monkeypatch, count, limit):
    run, executor = Mock(), Mock()
    monkeypatch.setattr(use_case, "ThreadPoolExecutor", executor)
    with pytest.raises(ValueError, match="max_concurrent_accounts.*positive integer"):
        use_case.process_accounts(
            [object() for _ in range(count)], run_account=run, log=Mock(),
            max_concurrent_accounts=limit,
        )
    run.assert_not_called()
    executor.assert_not_called()


def test_submission_order_is_input_order(monkeypatch):
    executor_factory = use_case.ThreadPoolExecutor
    submitted = []

    def executor(**kwargs):
        pool = executor_factory(**kwargs)
        original = pool.submit

        def submit(fn, config):
            submitted.append(config)
            return original(fn, config)

        pool.submit = submit
        return pool

    monkeypatch.setattr(use_case, "ThreadPoolExecutor", executor)
    configs = [SimpleNamespace(operator_id=str(i)) for i in range(5)]
    use_case.process_accounts(
        configs, run_account=lambda config: (config.operator_id, True), log=Mock(),
        max_concurrent_accounts=2,
    )
    assert submitted == configs
