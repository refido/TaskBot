from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from typing import Any, DefaultDict

from src.infrastructure.reporting.classification import (
    _APPLICATION_ERROR_LABEL,
    _FAILED_PUZZLE_SOLVE_STATUS,
    _UNREGISTERED_STATUS,
)
from src.infrastructure.reporting.models import TransactionRow, parse_iso


class MetricsCalculator:
    """Calculates analytics and metrics from transaction data."""

    def __init__(self, rows: list[TransactionRow], *, incremental: bool = False):
        self.rows = rows
        self._incremental = incremental
        if incremental:
            self._counts = defaultdict(int)
            self._durations = {}
            self._puzzles = defaultdict(int)
            self._skip_reasons = defaultdict(int)
            self._error_types = defaultdict(int)
            self._error_order = {}
            self._top_error_types = []
            self._error_labels = defaultdict(int)
            for row in rows:
                self._accumulate(row)

    def add_row(self, row: TransactionRow) -> None:
        """Extend an opt-in cache after terminal persistence has succeeded."""
        if not self._incremental:
            raise RuntimeError("add_row requires an incremental calculator")
        self._accumulate(row)
        self.rows.append(row)

    def _accumulate(self, row: TransactionRow) -> None:
        self._counts[row.status] += 1
        self._add_duration(("status", row.status), row.duration_seconds)
        self._add_duration("all", row.duration_seconds)
        if row.status == "completed":
            self._add_duration("completed", row.duration_seconds)
        if row.puzzle_solved is not None:
            self._puzzles["total"] += 1
            self._puzzles["solved"] += row.puzzle_solved is True
            self._puzzles["failed"] += row.puzzle_solved is False
            self._puzzles["attempts"] += row.puzzle_attempts
            self._puzzles["retried"] += row.puzzle_retry_count > 0
            self._puzzles["retries"] += row.puzzle_retry_count
            if row.puzzle_solved is True:
                self._add_duration("solved", row.duration_seconds)
            elif row.puzzle_solved is False:
                self._add_duration("failed", row.duration_seconds)
        if (
            row.status.startswith("skipped_")
            and row.status != _UNREGISTERED_STATUS
            and row.reason
        ):
            self._skip_reasons[row.reason] += 1
        if row.status == "error":
            error_type = row.reason.split("\n")[0][:100] if row.reason else "unknown_error"
            self._error_order.setdefault(error_type, len(self._error_order))
            self._error_types[error_type] += 1
            self._error_labels[row.error_label or _APPLICATION_ERROR_LABEL] += 1
            # Only this type's count changed. Re-rank at most eleven candidates,
            # retaining the legacy stable first-seen tie order for the top ten.
            candidates = self._top_error_types
            if error_type not in candidates:
                candidates = [*candidates, error_type]
            self._top_error_types = sorted(
                candidates,
                key=lambda key: (-self._error_types[key], self._error_order[key]),
            )[:10]

    def _add_duration(self, key: Any, value: float) -> None:
        if not value > 0:
            return
        # Retain Python 3.14 sum's compensated floating-point accumulation,
        # including its non-finite behavior, without retaining/scanning samples.
        stats = self._durations.setdefault(key, [0, 0.0, 0.0, value, value])
        count, high, low, minimum, maximum = stats
        total = high + value
        if abs(high) >= abs(value):
            low += (high - total) + value
        else:
            low += (value - total) + high
        stats[:] = [count + 1, total, low, min(minimum, value), max(maximum, value)]

    def _duration_average(self, key: Any) -> float:
        stats = self._durations.get(key)
        if stats is None:
            return 0.0
        count, high, low, _, _ = stats
        total = high + low if low and isfinite(low) else high
        return round(total / count, 3)

    def get_summary(self) -> dict[str, int]:
        """Get count summary by status."""
        if self._incremental:
            return {**self._counts, "total": len(self.rows)}
        counts: DefaultDict[str, int] = defaultdict(int)
        for row in self.rows:
            counts[row.status] += 1
        counts["total"] = len(self.rows)
        return dict(counts)

    def get_analytics(self, run_started_at: str) -> dict[str, Any]:
        """Generate comprehensive analytics."""
        if not self.rows:
            return self._empty_analytics()

        return {
            "summary": self._calculate_summary(),
            "performance": self._calculate_performance(run_started_at),
            "puzzle_metrics": self._calculate_puzzle_metrics(),
            "breakdown_by_status": self._get_status_breakdown(),
            "skip_reasons": self._get_skip_reasons(),
            "error_analysis": self._get_error_analysis(),
        }

    def _calculate_summary(self) -> dict[str, Any]:
        total = len(self.rows)
        counts = self.get_summary()

        completed = counts.get("completed", 0)
        failed = counts.get("error", 0)
        failed_puzzle_solve = counts.get(_FAILED_PUZZLE_SOLVE_STATUS, 0)
        unregistered = counts.get(_UNREGISTERED_STATUS, 0)
        skipped = sum(
            counts.get(status, 0)
            for status in counts
            if status.startswith("skipped_") and status != _UNREGISTERED_STATUS
        )

        return {
            "total_transactions": total,
            "completed": completed,
            "failed": failed,
            "failed_puzzle_solve": failed_puzzle_solve,
            "skipped": skipped,
            "unregistered": unregistered,
            "success_rate_percent": self._safe_percentage(completed, total),
            "failed_rate_percent": self._safe_percentage(failed, total),
            "failed_puzzle_solve_rate_percent": self._safe_percentage(
                failed_puzzle_solve, total
            ),
            "skip_rate_percent": self._safe_percentage(skipped, total),
            "unregistered_rate_percent": self._safe_percentage(unregistered, total),
        }

    def _calculate_performance(self, run_started_at: str) -> dict[str, Any]:
        if self._incremental:
            total_runtime, throughput = self._compute_runtime_and_throughput(run_started_at)
            stats = self._durations.get("all", [0, 0.0, 0.0, 0.0, 0.0])
            return {
                "total_runtime_seconds": round(total_runtime, 2),
                "total_runtime_minutes": round(total_runtime / 60, 2),
                "throughput_per_minute": round(throughput, 2),
                "avg_duration_seconds": self._duration_average("all"),
                "min_duration_seconds": round(stats[3], 3),
                "max_duration_seconds": round(stats[4], 3),
                "avg_completed_duration_seconds": self._duration_average("completed"),
            }
        durations = [row.duration_seconds for row in self.rows if row.duration_seconds > 0]
        completed_durations = [
            row.duration_seconds
            for row in self.rows
            if row.status == "completed" and row.duration_seconds > 0
        ]

        total_runtime, throughput = self._compute_runtime_and_throughput(run_started_at)

        return {
            "total_runtime_seconds": round(total_runtime, 2),
            "total_runtime_minutes": round(total_runtime / 60, 2),
            "throughput_per_minute": round(throughput, 2),
            "avg_duration_seconds": self._safe_average(durations),
            "min_duration_seconds": round(min(durations), 3) if durations else 0.0,
            "max_duration_seconds": round(max(durations), 3) if durations else 0.0,
            "avg_completed_duration_seconds": self._safe_average(completed_durations),
        }

    def _compute_runtime_and_throughput(
        self, run_started_at: str
    ) -> tuple[float, float]:
        try:
            run_start = parse_iso(run_started_at)
            run_end = datetime.now().astimezone()
            total_runtime = (run_end - run_start).total_seconds()
            throughput = (
                len(self.rows) / (total_runtime / 60) if total_runtime > 0 else 0.0
            )
            return total_runtime, throughput
        except Exception:
            return 0.0, 0.0

    def _calculate_puzzle_metrics(self) -> dict[str, Any]:
        if self._incremental:
            puzzles = self._puzzles
            total = puzzles.get("total", 0)
            solved, failed = puzzles.get("solved", 0), puzzles.get("failed", 0)
            attempts = puzzles.get("attempts", 0)
            return {
                "total_puzzles": total,
                "puzzles_solved": solved,
                "puzzles_failed": failed,
                "puzzle_success_rate_percent": self._safe_percentage(solved, total),
                "puzzle_failure_rate_percent": self._safe_percentage(failed, total),
                "avg_attempts": round(attempts / total, 2) if total else 0.0,
                "total_attempts": attempts,
                "retried_puzzles": puzzles.get("retried", 0),
                "total_retries": puzzles.get("retries", 0),
                "avg_solved_duration_seconds": self._duration_average("solved"),
                "avg_failed_duration_seconds": self._duration_average("failed"),
            }
        puzzle_rows = [row for row in self.rows if row.puzzle_solved is not None]
        if not puzzle_rows:
            return {
                "total_puzzles": 0,
                "puzzles_solved": 0,
                "puzzles_failed": 0,
                "puzzle_success_rate_percent": 0.0,
                "puzzle_failure_rate_percent": 0.0,
                "avg_attempts": 0.0,
                "total_attempts": 0,
                "retried_puzzles": 0,
                "total_retries": 0,
                "avg_solved_duration_seconds": 0.0,
                "avg_failed_duration_seconds": 0.0,
            }

        total_puzzles = len(puzzle_rows)
        solved = sum(1 for row in puzzle_rows if row.puzzle_solved is True)
        failed = sum(1 for row in puzzle_rows if row.puzzle_solved is False)
        total_attempts = sum(row.puzzle_attempts for row in puzzle_rows)
        retried_puzzles = sum(1 for row in puzzle_rows if row.puzzle_retry_count > 0)
        total_retries = sum(row.puzzle_retry_count for row in puzzle_rows)

        solved_durations = [
            row.duration_seconds
            for row in puzzle_rows
            if row.puzzle_solved is True and row.duration_seconds > 0
        ]
        failed_durations = [
            row.duration_seconds
            for row in puzzle_rows
            if row.puzzle_solved is False and row.duration_seconds > 0
        ]

        return {
            "total_puzzles": total_puzzles,
            "puzzles_solved": solved,
            "puzzles_failed": failed,
            "puzzle_success_rate_percent": self._safe_percentage(solved, total_puzzles),
            "puzzle_failure_rate_percent": self._safe_percentage(failed, total_puzzles),
            "avg_attempts": round(total_attempts / total_puzzles, 2)
            if total_puzzles > 0
            else 0.0,
            "total_attempts": total_attempts,
            "retried_puzzles": retried_puzzles,
            "total_retries": total_retries,
            "avg_solved_duration_seconds": self._safe_average(solved_durations),
            "avg_failed_duration_seconds": self._safe_average(failed_durations),
        }

    def _get_status_breakdown(self) -> dict[str, Any]:
        if self._incremental:
            return {
                status: {
                    "count": count,
                    "percentage": self._safe_percentage(count, len(self.rows)),
                    "avg_duration_seconds": self._duration_average(("status", status)),
                }
                for status, count in self._counts.items()
            }
        breakdown: DefaultDict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "durations": []}
        )

        for row in self.rows:
            breakdown[row.status]["count"] += 1
            if row.duration_seconds > 0:
                breakdown[row.status]["durations"].append(row.duration_seconds)

        total = len(self.rows)
        result: dict[str, Any] = {}
        for status, data in breakdown.items():
            durations = data["durations"]
            result[status] = {
                "count": data["count"],
                "percentage": self._safe_percentage(data["count"], total),
                "avg_duration_seconds": self._safe_average(durations),
            }
        return result

    def _get_skip_reasons(self) -> dict[str, int]:
        if self._incremental:
            return dict(self._skip_reasons)
        skip_reasons: DefaultDict[str, int] = defaultdict(int)
        for row in self.rows:
            if (
                row.status.startswith("skipped_")
                and row.status != _UNREGISTERED_STATUS
                and row.reason
            ):
                skip_reasons[row.reason] += 1
        return dict(skip_reasons)

    def _get_error_analysis(self) -> dict[str, Any]:
        if self._incremental:
            return {
                "total_errors": self._counts.get("error", 0),
                "unique_error_types": len(self._error_types),
                "error_frequency": {
                    key: self._error_types[key] for key in self._top_error_types
                },
                "error_labels": dict(sorted(self._error_labels.items())),
            }
        error_types: DefaultDict[str, int] = defaultdict(int)
        error_labels: DefaultDict[str, int] = defaultdict(int)
        for row in self.rows:
            if row.status != "error":
                continue

            error_type = row.reason.split("\n")[0][:100] if row.reason else "unknown_error"
            error_types[error_type] += 1
            error_label = row.error_label or _APPLICATION_ERROR_LABEL
            error_labels[error_label] += 1

        return {
            "total_errors": sum(error_types.values()),
            "unique_error_types": len(error_types),
            "error_frequency": dict(
                sorted(error_types.items(), key=lambda item: item[1], reverse=True)[:10]
            ),
            "error_labels": dict(sorted(error_labels.items(), key=lambda item: item[0])),
        }

    @staticmethod
    def _safe_percentage(value: int, total: int) -> float:
        return round((value / total * 100), 2) if total > 0 else 0.0

    @staticmethod
    def _safe_average(values: list[float]) -> float:
        return round(sum(values) / len(values), 3) if values else 0.0

    @staticmethod
    def _empty_analytics() -> dict[str, Any]:
        return {
            "summary": {
                "total_transactions": 0,
                "completed": 0,
                "failed": 0,
                "failed_puzzle_solve": 0,
                "skipped": 0,
                "unregistered": 0,
                "success_rate_percent": 0.0,
                "failed_rate_percent": 0.0,
                "failed_puzzle_solve_rate_percent": 0.0,
                "skip_rate_percent": 0.0,
                "unregistered_rate_percent": 0.0,
            },
            "performance": {
                "total_runtime_seconds": 0.0,
                "total_runtime_minutes": 0.0,
                "throughput_per_minute": 0.0,
                "avg_duration_seconds": 0.0,
                "min_duration_seconds": 0.0,
                "max_duration_seconds": 0.0,
                "avg_completed_duration_seconds": 0.0,
            },
            "puzzle_metrics": {},
            "breakdown_by_status": {},
            "skip_reasons": {},
            "error_analysis": {
                "total_errors": 0,
                "unique_error_types": 0,
                "error_frequency": {},
                "error_labels": {},
            },
        }
