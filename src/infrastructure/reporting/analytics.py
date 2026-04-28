from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, DefaultDict

from src.infrastructure.reporting.classification import (
    _APPLICATION_ERROR_LABEL,
    _FAILED_PUZZLE_SOLVE_STATUS,
    _UNREGISTERED_STATUS,
)
from src.infrastructure.reporting.models import TransactionRow, parse_iso


class MetricsCalculator:
    """Calculates analytics and metrics from transaction data."""

    def __init__(self, rows: list[TransactionRow]):
        self.rows = rows

    def get_summary(self) -> dict[str, int]:
        """Get count summary by status."""
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
