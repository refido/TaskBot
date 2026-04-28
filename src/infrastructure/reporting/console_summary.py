from __future__ import annotations

from typing import Any, Callable


def print_skipped_niks(reporter: Any, log_print_fn: Callable[..., None]) -> None:
    skipped_by_type = reporter.get_skipped_niks_by_type()

    if not skipped_by_type:
        return

    log_print_fn("\nSkipped NIKs by Type:")
    for skip_type, niks in skipped_by_type.items():
        log_print_fn(f"  {skip_type}: {len(niks)} NIKs")
        if len(niks) <= 5:
            for nik in niks:
                log_print_fn(f"    - {nik}")
        else:
            log_print_fn(f"    First 5: {', '.join(niks[:5])}")
            log_print_fn(f"    ... and {len(niks) - 5} more")


def print_unregistered_niks(reporter: Any, log_print_fn: Callable[..., None]) -> None:
    unregistered_niks = reporter.get_unregistered_niks()

    if not unregistered_niks:
        return

    log_print_fn("\nUnregistered NIKs:")
    log_print_fn(f"  not_registered: {len(unregistered_niks)} NIKs")
    if len(unregistered_niks) <= 5:
        for nik in unregistered_niks:
            log_print_fn(f"    - {nik}")
    else:
        log_print_fn(f"    First 5: {', '.join(unregistered_niks[:5])}")
        log_print_fn(f"    ... and {len(unregistered_niks) - 5} more")


def print_nik_statistics(reporter: Any, log_print_fn: Callable[..., None]) -> None:
    log_print_fn("\nNIK Statistics:")
    log_print_fn(f"  Total Successful: {len(reporter.get_successful_niks())}")
    log_print_fn(f"  Total Failed: {len(reporter.get_failed_niks())}")
    log_print_fn(
        "  Total Failed Puzzle Solve: "
        f"{len(reporter.get_failed_puzzle_solve_niks())}"
    )

    skipped_by_type = reporter.get_skipped_niks_by_type()
    total_skipped = sum(len(niks) for niks in skipped_by_type.values())
    log_print_fn(f"  Total Skipped: {total_skipped}")
    log_print_fn(f"  Total Unregistered: {len(reporter.get_unregistered_niks())}")

    puzzle_failed = reporter.get_puzzle_failed_niks()
    if puzzle_failed:
        log_print_fn(f"  Puzzle Failed: {len(puzzle_failed)}")


def print_section(
    title: str,
    data: dict[str, Any],
    log_print_fn: Callable[..., None],
    filters: list[str] | None = None,
    suffix: str = "",
) -> None:
    log_print_fn(f"\n{title}:")
    for key, value in data.items():
        if filters:
            if suffix:
                if not any(filter_value in key for filter_value in filters):
                    continue
            else:
                if any(filter_value in key for filter_value in filters):
                    continue

        label = key.replace("_", " ").title()
        if isinstance(value, float):
            log_print_fn(f"  {label}: {value:.2f}{'%' if '_percent' in key else ''}")
        else:
            log_print_fn(f"  {label}: {value}")


def print_performance(perf: dict[str, Any], log_print_fn: Callable[..., None]) -> None:
    log_print_fn("\nPerformance Metrics:")
    log_print_fn(f"  Total Runtime: {perf['total_runtime_minutes']:.2f} minutes")
    log_print_fn(f"  Throughput: {perf['throughput_per_minute']:.2f} items/minute")
    log_print_fn(f"  Avg Duration: {perf['avg_duration_seconds']:.3f} seconds")
    if perf["avg_completed_duration_seconds"] > 0:
        log_print_fn(
            f"  Avg Completed Duration: {perf['avg_completed_duration_seconds']:.3f} seconds"
        )


def print_puzzle_metrics(
    puzzle: dict[str, Any], log_print_fn: Callable[..., None]
) -> None:
    if puzzle.get("total_puzzles", 0) <= 0:
        return

    log_print_fn("\nPuzzle Solving Metrics:")
    log_print_fn(f"  Total Puzzles: {puzzle['total_puzzles']}")
    log_print_fn(
        f"  Solved: {puzzle['puzzles_solved']} ({puzzle['puzzle_success_rate_percent']}%)"
    )
    log_print_fn(
        f"  Failed: {puzzle['puzzles_failed']} ({puzzle['puzzle_failure_rate_percent']}%)"
    )
    log_print_fn(f"  Avg Attempts: {puzzle['avg_attempts']:.2f}")
    if puzzle["retried_puzzles"] > 0:
        log_print_fn(f"  Retried Puzzles: {puzzle['retried_puzzles']}")
        log_print_fn(f"  Total Retries: {puzzle['total_retries']}")

    if puzzle["avg_solved_duration_seconds"] > 0:
        log_print_fn(f"  Avg Solve Time: {puzzle['avg_solved_duration_seconds']:.3f}s")
    if puzzle["avg_failed_duration_seconds"] > 0:
        log_print_fn(
            f"  Avg Failed Time: {puzzle['avg_failed_duration_seconds']:.3f}s"
        )


def print_status_breakdown(
    breakdown: dict[str, Any], log_print_fn: Callable[..., None]
) -> None:
    log_print_fn("\nStatus Breakdown:")
    for status, data in breakdown.items():
        log_print_fn(
            f"  {status}: {data['count']} ({data['percentage']}%) - "
            f"avg {data['avg_duration_seconds']:.3f}s"
        )


def print_skip_reasons(
    reasons: dict[str, int], log_print_fn: Callable[..., None]
) -> None:
    if not reasons:
        return

    log_print_fn("\nTop Skip Reasons:")
    for reason, count in list(reasons.items())[:5]:
        log_print_fn(f"  {reason}: {count}")


def print_error_analysis(
    analysis: dict[str, Any], log_print_fn: Callable[..., None]
) -> None:
    if analysis["total_errors"] <= 0:
        return

    log_print_fn("\nError Analysis:")
    log_print_fn(f"  Total Errors: {analysis['total_errors']}")
    log_print_fn(f"  Unique Error Types: {analysis['unique_error_types']}")
    if analysis["error_labels"]:
        log_print_fn("  Error Labels:")
        for error_label, count in analysis["error_labels"].items():
            log_print_fn(f"    {error_label}: {count}")
    if analysis["error_frequency"]:
        log_print_fn("  Top Errors:")
        for error, count in list(analysis["error_frequency"].items())[:3]:
            log_print_fn(f"    {error[:80]}...: {count}")
