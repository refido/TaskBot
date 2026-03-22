import csv
import json
import os
import traceback
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional

from src.logging_utils import log_print, logger
from src.path_utils import build_dated_dir, build_timestamped_run_dir

_UNREGISTERED_SKIP_TYPE = "not_registered"
_UNREGISTERED_STATUS = f"skipped_{_UNREGISTERED_SKIP_TYPE}"
_UNREGISTERED_REASON_MARKERS = ("pelanggan tidak terdaftar", "not registered")


def now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso(iso_str: str) -> datetime:
    """Parse ISO format timestamp to datetime object."""
    try:
        return datetime.fromisoformat(iso_str)
    except Exception:
        # Preserve original behavior: fallback to "now" on any parsing error.
        return datetime.now().astimezone()


@dataclass
class TransactionRow:
    """Data model for a single transaction record."""

    nik: str
    status: str
    operator: str = ""
    started_at: str = ""
    finished_at: str = ""
    url: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    puzzle_solved: Optional[bool] = None
    puzzle_attempts: int = 0
    reason: str = ""

    def compute_duration(self) -> None:
        """Calculate duration between started_at and finished_at."""
        if not (self.started_at and self.finished_at):
            return

        try:
            start = parse_iso(self.started_at)
            finish = parse_iso(self.finished_at)
            self.duration_seconds = (finish - start).total_seconds()
        except Exception:
            # Preserve original behavior: default to 0.0 on error.
            self.duration_seconds = 0.0


class FileWriter:
    """Handles file I/O operations for transaction data."""

    _CSV_FIELDNAMES: List[str] = [
        "operator",
        "nik",
        "status",
        "started_at",
        "finished_at",
        "duration_seconds",
        "puzzle_solved",
        "puzzle_attempts",
        "url",
        "error",
        "reason",
    ]

    def __init__(self, csv_path: Path, jsonl_path: Path):
        self.csv_path = csv_path
        self.jsonl_path = jsonl_path
        self.fieldnames = list(self._CSV_FIELDNAMES)

    # Public methods
    def init_csv(self) -> None:
        """Initialize CSV file with headers if needed."""
        needs_header = not (self.csv_path.exists() and self.csv_path.stat().st_size > 0)
        with self.csv_path.open("a", newline="", encoding="utf-8") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=self.fieldnames)
            if needs_header:
                writer.writeheader()
                self._flush_file(file_handle)

    def append_row(self, row: TransactionRow) -> None:
        """Append a row to both CSV and JSONL files."""
        self._append_to_csv(row)
        self._append_to_jsonl(row)

    def write_json(self, path: Path, data: dict) -> None:
        """Write JSON data to file."""
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Private helpers
    def _append_to_csv(self, row: TransactionRow) -> None:
        with self.csv_path.open("a", newline="", encoding="utf-8") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=self.fieldnames)
            writer.writerow(asdict(row))
            self._flush_file(file_handle)

    def _append_to_jsonl(self, row: TransactionRow) -> None:
        with self.jsonl_path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
            self._flush_file(file_handle)

    @staticmethod
    def _flush_file(file_handle) -> None:
        """Flush and sync file to disk."""
        file_handle.flush()
        try:
            os.fsync(file_handle.fileno())
        except Exception:
            # Best-effort fsync; preserve original behavior.
            pass


class MetricsCalculator:
    """Calculates analytics and metrics from transaction data."""

    def __init__(self, rows: List[TransactionRow]):
        self.rows = rows

    # Public methods
    def get_summary(self) -> Dict[str, int]:
        """Get count summary by status."""
        counts: DefaultDict[str, int] = defaultdict(int)
        for row in self.rows:
            counts[row.status] += 1
        counts["total"] = len(self.rows)
        return dict(counts)

    def get_analytics(self, run_started_at: str) -> Dict[str, Any]:
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

    # Private helpers
    def _calculate_summary(self) -> Dict[str, Any]:
        total = len(self.rows)
        counts = self.get_summary()

        completed = counts.get("completed", 0)
        errors = counts.get("error", 0)
        unregistered = counts.get(_UNREGISTERED_STATUS, 0)
        skipped = sum(
            counts.get(k, 0)
            for k in counts
            if k.startswith("skipped_") and k != _UNREGISTERED_STATUS
        )

        return {
            "total_transactions": total,
            "completed": completed,
            "errors": errors,
            "skipped": skipped,
            "unregistered": unregistered,
            "success_rate_percent": self._safe_percentage(completed, total),
            "error_rate_percent": self._safe_percentage(errors, total),
            "skip_rate_percent": self._safe_percentage(skipped, total),
            "unregistered_rate_percent": self._safe_percentage(unregistered, total),
        }

    def _calculate_performance(self, run_started_at: str) -> Dict[str, Any]:
        durations = [r.duration_seconds for r in self.rows if r.duration_seconds > 0]
        completed_durations = [
            r.duration_seconds
            for r in self.rows
            if r.status == "completed" and r.duration_seconds > 0
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
            # Preserve original behavior.
            return 0.0, 0.0

    def _calculate_puzzle_metrics(self) -> Dict[str, Any]:
        puzzle_rows = [r for r in self.rows if r.puzzle_solved is not None]
        if not puzzle_rows:
            return {
                "total_puzzles": 0,
                "puzzles_solved": 0,
                "puzzles_failed": 0,
                "puzzle_success_rate_percent": 0.0,
                "puzzle_failure_rate_percent": 0.0,
                "avg_attempts": 0.0,
                "total_attempts": 0,
                "avg_solved_duration_seconds": 0.0,
                "avg_failed_duration_seconds": 0.0,
            }

        total_puzzles = len(puzzle_rows)
        solved = sum(1 for r in puzzle_rows if r.puzzle_solved is True)
        failed = sum(1 for r in puzzle_rows if r.puzzle_solved is False)
        total_attempts = sum(r.puzzle_attempts for r in puzzle_rows)

        solved_durations = [
            r.duration_seconds
            for r in puzzle_rows
            if r.puzzle_solved is True and r.duration_seconds > 0
        ]
        failed_durations = [
            r.duration_seconds
            for r in puzzle_rows
            if r.puzzle_solved is False and r.duration_seconds > 0
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
            "avg_solved_duration_seconds": self._safe_average(solved_durations),
            "avg_failed_duration_seconds": self._safe_average(failed_durations),
        }

    def _get_status_breakdown(self) -> Dict[str, Any]:
        breakdown: DefaultDict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "durations": []}
        )

        for row in self.rows:
            breakdown[row.status]["count"] += 1
            if row.duration_seconds > 0:
                breakdown[row.status]["durations"].append(row.duration_seconds)

        total = len(self.rows)
        result: Dict[str, Any] = {}
        for status, data in breakdown.items():
            durations = data["durations"]
            result[status] = {
                "count": data["count"],
                "percentage": self._safe_percentage(data["count"], total),
                "avg_duration_seconds": self._safe_average(durations),
            }
        return result

    def _get_skip_reasons(self) -> Dict[str, int]:
        skip_reasons: DefaultDict[str, int] = defaultdict(int)
        for row in self.rows:
            if (
                row.status.startswith("skipped_")
                and row.status != _UNREGISTERED_STATUS
                and row.reason
            ):
                skip_reasons[row.reason] += 1
        return dict(skip_reasons)

    def _get_error_analysis(self) -> Dict[str, Any]:
        error_types: DefaultDict[str, int] = defaultdict(int)
        for row in self.rows:
            if row.status == "error" and row.reason:
                error_type = row.reason.split("\n")[0][:100]
                error_types[error_type] += 1

        return {
            "total_errors": sum(error_types.values()),
            "unique_error_types": len(error_types),
            "error_frequency": dict(
                sorted(error_types.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
        }

    @staticmethod
    def _safe_percentage(value: int, total: int) -> float:
        return round((value / total * 100), 2) if total > 0 else 0.0

    @staticmethod
    def _safe_average(values: List[float]) -> float:
        return round(sum(values) / len(values), 3) if values else 0.0

    @staticmethod
    def _empty_analytics() -> Dict[str, Any]:
        return {
            "summary": {
                "total_transactions": 0,
                "completed": 0,
                "errors": 0,
                "skipped": 0,
                "unregistered": 0,
                "success_rate_percent": 0.0,
                "error_rate_percent": 0.0,
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
            "error_analysis": {},
        }


class TransactionReporter:
    """Main reporter class for managing transaction logging and analytics."""

    def __init__(
        self,
        out_dir: str = "reports",
        run_name: Optional[str] = None,
        per_run_subdir: bool = True,
        operator: Optional[str] = None,
    ):
        self.operator = operator or ""
        self.run_started_at = now_iso()
        self.rows: List[TransactionRow] = []

        self._setup_directories(out_dir, run_name, per_run_subdir)

        self.file_writer = FileWriter(self.csv_path, self.jsonl_path)
        self.file_writer.init_csv()

        if not self.jsonl_path.exists():
            self.jsonl_path.touch()

        self._write_meta()

    # Public methods (external API)
    def start_item(self, nik: str) -> str:
        """Start timing for a new item."""
        return now_iso()

    def complete(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        puzzle_solved: Optional[bool] = None,
        puzzle_attempts: int = 0,
        reason: str = "",
    ) -> None:
        """Record a completed transaction."""
        self._add_row(
            status="completed",
            nik=nik,
            started_at=started_at,
            url=url,
            puzzle_solved=puzzle_solved,
            puzzle_attempts=puzzle_attempts,
            reason=reason,
        )

    def skip(
        self,
        nik: str,
        started_at: str,
        skip_type: str,
        url: str = "",
        reason: str = "",
    ) -> None:
        """Record a skipped transaction with specific type."""
        status = f"skipped_{skip_type}"
        self._add_row(
            status=status, nik=nik, started_at=started_at, url=url, reason=reason
        )

    def skip_max_kuota(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = "Max kuota alert",
    ) -> None:
        """Record max kuota skip."""
        self.skip(nik, started_at, "max_kuota", url, reason)

    def skip_out_of_stock(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = "Sellable stock is empty",
    ) -> None:
        """Record out-of-stock stop."""
        self.skip(nik, started_at, "out_of_stock", url, reason)

    def skip_needs_update(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = "Needs data update",
    ) -> None:
        """Record needs update skip."""
        self.skip(nik, started_at, "needs_update", url, reason)

    def skip_not_registered(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = "Pelanggan Tidak Terdaftar",
    ) -> None:
        """Record not registered skip."""
        self.skip(nik, started_at, "not_registered", url, reason)

    def error(
        self,
        nik: str,
        started_at: str,
        exc: Exception,
        url: str = "",
        puzzle_solved: Optional[bool] = None,
        puzzle_attempts: int = 0,
    ) -> None:
        """Record an error."""
        reason = str(exc)
        error_details = traceback.format_exc()
        status = (
            _UNREGISTERED_STATUS
            if self._reason_indicates_unregistered(f"{reason}\n{error_details}")
            else "error"
        )
        row = self._create_row(
            status=status,
            nik=nik,
            started_at=started_at,
            url=url,
            puzzle_solved=puzzle_solved,
            puzzle_attempts=puzzle_attempts,
            reason=reason,
            error=error_details,
        )
        self._record_row(row)

    def write_files(self, run_name: Optional[str] = None) -> None:
        """Write final snapshot files and update operator summary."""
        # NOTE: run_name is kept for backward compatibility; original code did not use it.
        calculator = MetricsCalculator(self.rows)
        mapping_report = self.get_mapping_report()
        payload = {
            "operator": self.operator,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": calculator.get_summary(),
            "analytics": calculator.get_analytics(self.run_started_at),
            "items": [asdict(r) for r in self.rows],
            "mapping_report": mapping_report,
            "nik_lists": {
                **mapping_report,
                "errors_by_reason": self.get_error_niks_by_reason(),
                "other_statuses": self.get_other_status_niks_by_status(),
                "puzzle_failed": self.get_puzzle_failed_niks(),
            },
            "puzzle_stats_by_nik": self.get_puzzle_stats_by_nik(),
        }

        self.file_writer.write_json(self.final_json_path, payload)
        self.file_writer.write_json(
            self.analytics_path, calculator.get_analytics(self.run_started_at)
        )

        self._write_operator_summary()
        logger.bind(
            event="report.files_written",
            operator=self.operator,
            run_dir=str(self.run_dir),
            row_count=len(self.rows),
            counts=payload["counts"],
            snapshot_path=str(self.final_json_path),
            csv_path=str(self.csv_path),
            jsonl_path=str(self.jsonl_path),
            analytics_path=str(self.analytics_path),
        ).info("Run report files written")

        log_print(
            f"Report written: {self.final_json_path}, {self.csv_path}, "
            f"{self.jsonl_path}, {self.analytics_path}"
        )

    def summary(self) -> Dict[str, int]:
        """Get summary counts."""
        return MetricsCalculator(self.rows).get_summary()

    def get_analytics(self) -> Dict[str, Any]:
        """Get comprehensive analytics."""
        return MetricsCalculator(self.rows).get_analytics(self.run_started_at)

    def get_rows_by_status(self, status: str) -> List[TransactionRow]:
        """Filter rows by status."""
        return [r for r in self.rows if r.status == status]

    def get_failed_niks(self) -> List[str]:
        """Get list of failed NIKs (error rows only)."""
        return [
            r.nik
            for r in self.rows
            if r.status == "error" and not self._is_unregistered_row(r)
        ]

    def get_successful_niks(self) -> List[str]:
        """Get list of successful NIKs."""
        return [r.nik for r in self.rows if r.status == "completed"]

    def get_skipped_niks_by_type(
        self, include_unregistered: bool = False
    ) -> Dict[str, List[str]]:
        """Get skipped NIKs grouped by skip type."""
        skipped_by_type: DefaultDict[str, List[str]] = defaultdict(list)
        for row in self.rows:
            if row.status.startswith("skipped_"):
                skip_type = row.status.replace("skipped_", "")
                if skip_type == _UNREGISTERED_SKIP_TYPE and not include_unregistered:
                    continue
                skipped_by_type[skip_type].append(row.nik)
        return dict(skipped_by_type)

    def get_unregistered_niks(self) -> List[str]:
        """Get NIKs flagged as 'Pelanggan Tidak Terdaftar'."""
        return [r.nik for r in self.rows if self._is_unregistered_row(r)]

    def get_mapping_report(self) -> Dict[str, Any]:
        """Build the main mapping report buckets for the current run."""
        return {
            "failed": self.get_failed_niks(),
            "successful": self.get_successful_niks(),
            "skipped": self.get_skipped_niks_by_type(),
            "unregistered": self.get_unregistered_niks(),
        }

    def get_error_niks_by_reason(self) -> Dict[str, List[str]]:
        """Get failed NIKs grouped by normalized error reason."""
        grouped: DefaultDict[str, List[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != "error" or self._is_unregistered_row(row):
                continue
            grouped[self._normalize_error_reason(row.reason)].append(row.nik)
        return dict(grouped)

    def get_other_status_niks_by_status(self) -> Dict[str, List[str]]:
        """Get NIKs grouped by any non-standard status."""
        grouped: DefaultDict[str, List[str]] = defaultdict(list)
        for row in self.rows:
            if row.status in {"completed", "error"} or row.status.startswith(
                "skipped_"
            ):
                continue
            grouped[row.status].append(row.nik)
        return dict(grouped)

    def get_puzzle_failed_niks(self) -> List[str]:
        """Get NIKs where puzzle solving failed."""
        return [r.nik for r in self.rows if r.puzzle_solved is False]

    def get_puzzle_stats_by_nik(self) -> Dict[str, Dict[str, Any]]:
        """Get puzzle statistics grouped by NIK."""
        nik_stats: DefaultDict[str, Dict[str, Any]] = defaultdict(
            lambda: {"attempts": 0, "solved": False}
        )
        for row in self.rows:
            if row.puzzle_solved is not None:
                nik_stats[row.nik]["attempts"] = row.puzzle_attempts
                nik_stats[row.nik]["solved"] = row.puzzle_solved
        return dict(nik_stats)

    def get_analytics_with_niks(self) -> Dict[str, Any]:
        """Get comprehensive analytics including NIK lists."""
        base_analytics = self.get_analytics()
        base_analytics["nik_details"] = {
            "mapping_report": self.get_mapping_report(),
            "successful_niks": self.get_successful_niks(),
            "failed_niks": self.get_failed_niks(),
            "skipped_by_type": self.get_skipped_niks_by_type(),
            "unregistered_niks": self.get_unregistered_niks(),
            "errors_by_reason": self.get_error_niks_by_reason(),
            "other_statuses": self.get_other_status_niks_by_status(),
            "puzzle_failed_niks": self.get_puzzle_failed_niks(),
            "puzzle_stats": self.get_puzzle_stats_by_nik(),
        }
        return base_analytics

    def print_summary(self) -> None:
        """Print comprehensive summary."""
        analytics = self.get_analytics()

        log_print("\n" + "=" * 60)
        log_print("RUN SUMMARY")
        log_print("=" * 60)

        self._print_section("Transaction Counts", analytics["summary"], ["_percent"])
        self._print_section(
            "Success Rates",
            analytics["summary"],
            ["success", "error", "skip", "unregistered"],
            suffix="_percent",
        )
        self._print_performance(analytics["performance"])
        self._print_puzzle_metrics(analytics["puzzle_metrics"])
        self._print_status_breakdown(analytics["breakdown_by_status"])
        self._print_skip_reasons(analytics["skip_reasons"])
        self._print_skipped_niks()
        self._print_unregistered_niks()
        self._print_error_analysis(analytics["error_analysis"])
        self._print_nik_statistics()

        log_print("\n" + "=" * 60)
        log_print(f"Analytics saved to: {self.analytics_path}")
        log_print("=" * 60 + "\n")

    # Protected-ish methods (kept private to preserve current design)
    def _setup_directories(
        self, out_dir: str, run_name: Optional[str], per_run_subdir: bool
    ) -> None:
        """Setup directory structure for reports organized by operator/email."""
        now_local = datetime.now().astimezone()
        safe_operator = self._sanitize_folder_name(self.operator)
        self.operator_dir = Path(out_dir) / safe_operator
        self.base_dir = build_dated_dir(self.operator_dir, now_local)

        if per_run_subdir:
            run_leaf = (
                self._sanitize_folder_name(run_name)
                if run_name
                else now_local.strftime("%H%M%S")
            )
            self.run_dir = build_timestamped_run_dir(
                self.operator_dir, now_local, run_leaf
            )
        else:
            self.run_dir = self.base_dir

        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.csv_path = self.run_dir / "items.csv"
        self.jsonl_path = self.run_dir / "items.jsonl"
        self.meta_path = self.run_dir / "run_meta.json"
        self.final_json_path = self.run_dir / "items_snapshot.json"
        self.analytics_path = self.run_dir / "analytics.json"

        self.operator_summary_path = self.operator_dir / "operator_summary.json"

    @staticmethod
    def _sanitize_folder_name(name: str) -> str:
        """Sanitize string for use as folder name."""
        if not name:
            return "unknown_operator"

        invalid_chars = '<>:"/\\|?*'
        sanitized = name
        for char in invalid_chars:
            sanitized = sanitized.replace(char, "_")

        sanitized = sanitized.strip(". ")
        sanitized = sanitized.replace(" ", "_")
        return sanitized if sanitized else "unknown_operator"

    @staticmethod
    def _normalize_error_reason(reason: str) -> str:
        """Build a short stable key for grouping errors."""
        if not reason:
            return "unknown_error"
        first_line = reason.splitlines()[0].strip()
        return first_line if first_line else "unknown_error"

    @staticmethod
    def _reason_indicates_unregistered(reason: str) -> bool:
        normalized = reason.casefold() if reason else ""
        return any(marker in normalized for marker in _UNREGISTERED_REASON_MARKERS)

    def _is_unregistered_row(self, row: TransactionRow) -> bool:
        if row.status == _UNREGISTERED_STATUS:
            return True
        if row.status != "error":
            return False
        return self._reason_indicates_unregistered(row.reason)

    # Private helpers (data recording)
    def _add_row(
        self,
        status: str,
        nik: str,
        started_at: str,
        url: str = "",
        puzzle_solved: Optional[bool] = None,
        puzzle_attempts: int = 0,
        reason: str = "",
        error: str = "",
    ) -> None:
        row = self._create_row(
            status=status,
            nik=nik,
            started_at=started_at,
            url=url,
            puzzle_solved=puzzle_solved,
            puzzle_attempts=puzzle_attempts,
            reason=reason,
            error=error,
        )
        self._record_row(row)

    def _create_row(
        self,
        status: str,
        nik: str,
        started_at: str,
        url: str = "",
        puzzle_solved: Optional[bool] = None,
        puzzle_attempts: int = 0,
        reason: str = "",
        error: str = "",
    ) -> TransactionRow:
        row = TransactionRow(
            operator=self.operator,
            nik=nik,
            status=status,
            started_at=started_at or self.run_started_at,
            finished_at=now_iso(),
            url=url,
            error=error,
            puzzle_solved=puzzle_solved,
            puzzle_attempts=puzzle_attempts,
            reason=reason,
        )
        row.compute_duration()
        return row

    def _record_row(self, row: TransactionRow) -> None:
        self.rows.append(row)
        self.file_writer.append_row(row)
        self._write_meta()
        logger.bind(
            event="report.row_recorded",
            operator=self.operator,
            nik=row.nik,
            status=row.status,
            duration_seconds=row.duration_seconds,
            puzzle_solved=row.puzzle_solved,
            puzzle_attempts=row.puzzle_attempts,
            reason=row.reason,
        ).info("Transaction row recorded")

    # Private helpers (meta + operator summary)
    def _write_meta(self) -> None:
        calculator = MetricsCalculator(self.rows)
        mapping_report = self.get_mapping_report()
        payload = {
            "operator": self.operator,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": calculator.get_summary(),
            "analytics": calculator.get_analytics(self.run_started_at),
            "mapping_report": mapping_report,
            "nik_lists": {
                **mapping_report,
                "errors_by_reason": self.get_error_niks_by_reason(),
                "other_statuses": self.get_other_status_niks_by_status(),
            },
            "files": {
                "csv": str(self.csv_path),
                "jsonl": str(self.jsonl_path),
                "final_snapshot": str(self.final_json_path),
                "analytics": str(self.analytics_path),
            },
            "paths": {"day_dir": str(self.base_dir), "run_dir": str(self.run_dir)},
        }
        self.file_writer.write_json(self.meta_path, payload)
        logger.bind(
            event="report.meta_written",
            operator=self.operator,
            run_dir=str(self.run_dir),
            counts=payload["counts"],
            meta_path=str(self.meta_path),
        ).debug("Run meta updated")

    def _write_operator_summary(self) -> None:
        """Write operator-level summary aggregating all runs."""
        if not self.operator_dir.exists():
            return

        all_runs: List[Dict[str, Any]] = []
        for meta_file in self.operator_dir.rglob("run_meta.json"):
            run_data = self._try_read_json(meta_file)
            if run_data is None:
                continue
            all_runs.append(
                {
                    "run_started_at": run_data.get("run_started_at"),
                    "run_ended_at": run_data.get("run_ended_at"),
                    "counts": run_data.get("counts", {}),
                    "run_dir": str(meta_file.parent),
                }
            )

        if not all_runs:
            return

        total_transactions = sum(
            run.get("counts", {}).get("total", 0) for run in all_runs
        )
        total_completed = sum(
            run.get("counts", {}).get("completed", 0) for run in all_runs
        )
        total_errors = sum(run.get("counts", {}).get("error", 0) for run in all_runs)
        total_unregistered = sum(
            run.get("counts", {}).get(_UNREGISTERED_STATUS, 0) for run in all_runs
        )
        total_skipped = sum(
            sum(
                count
                for status, count in run.get("counts", {}).items()
                if status.startswith("skipped_") and status != _UNREGISTERED_STATUS
            )
            for run in all_runs
        )

        summary = {
            "operator": self.operator,
            "last_updated": now_iso(),
            "total_runs": len(all_runs),
            "aggregated_stats": {
                "total_transactions": total_transactions,
                "total_completed": total_completed,
                "total_errors": total_errors,
                "total_skipped": total_skipped,
                "total_unregistered": total_unregistered,
                "success_rate_percent": MetricsCalculator._safe_percentage(
                    total_completed, total_transactions
                ),
            },
            "recent_runs": sorted(
                all_runs, key=lambda x: x["run_started_at"], reverse=True
            )[:10],
        }

        self.file_writer.write_json(self.operator_summary_path, summary)
        logger.bind(
            event="report.operator_summary_updated",
            operator=self.operator,
            total_runs=summary["total_runs"],
            total_transactions=total_transactions,
            total_completed=total_completed,
            total_errors=total_errors,
            total_skipped=total_skipped,
            total_unregistered=total_unregistered,
            operator_summary_path=str(self.operator_summary_path),
        ).info("Operator summary updated")
        log_print(f"Operator summary updated: {self.operator_summary_path}")

    def _try_read_json(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            with path.open("r", encoding="utf-8") as file_handle:
                return json.load(file_handle)
        except Exception as exc:
            logger.bind(
                event="report.json_read_error",
                operator=self.operator,
                path=str(path),
            ).exception("Error reading report JSON file")
            log_print(f"Error reading {path}: {exc}")
            return None

    # Private helpers (printing)
    def _print_skipped_niks(self) -> None:
        skipped_by_type = self.get_skipped_niks_by_type()

        if not skipped_by_type:
            return

        log_print("\nSkipped NIKs by Type:")
        for skip_type, niks in skipped_by_type.items():
            log_print(f"  {skip_type}: {len(niks)} NIKs")
            if len(niks) <= 5:
                for nik in niks:
                    log_print(f"    - {nik}")
            else:
                log_print(f"    First 5: {', '.join(niks[:5])}")
                log_print(f"    ... and {len(niks) - 5} more")

    def _print_unregistered_niks(self) -> None:
        unregistered_niks = self.get_unregistered_niks()

        if not unregistered_niks:
            return

        log_print("\nUnregistered NIKs:")
        log_print(f"  not_registered: {len(unregistered_niks)} NIKs")
        if len(unregistered_niks) <= 5:
            for nik in unregistered_niks:
                log_print(f"    - {nik}")
        else:
            log_print(f"    First 5: {', '.join(unregistered_niks[:5])}")
            log_print(f"    ... and {len(unregistered_niks) - 5} more")

    def _print_nik_statistics(self) -> None:
        log_print("\nNIK Statistics:")
        log_print(f"  Total Successful: {len(self.get_successful_niks())}")
        log_print(f"  Total Failed: {len(self.get_failed_niks())}")

        skipped_by_type = self.get_skipped_niks_by_type()
        total_skipped = sum(len(niks) for niks in skipped_by_type.values())
        log_print(f"  Total Skipped: {total_skipped}")
        log_print(f"  Total Unregistered: {len(self.get_unregistered_niks())}")

        puzzle_failed = self.get_puzzle_failed_niks()
        if puzzle_failed:
            log_print(f"  Puzzle Failed: {len(puzzle_failed)}")

    def _print_section(
        self,
        title: str,
        data: Dict[str, Any],
        filters: Optional[List[str]] = None,
        suffix: str = "",
    ) -> None:
        log_print(f"\n{title}:")
        for key, value in data.items():
            if filters:
                if suffix:
                    if not any(f in key for f in filters):
                        continue
                else:
                    if any(f in key for f in filters):
                        continue

            label = key.replace("_", " ").title()
            if isinstance(value, float):
                log_print(f"  {label}: {value:.2f}{'%' if '_percent' in key else ''}")
            else:
                log_print(f"  {label}: {value}")

    def _print_performance(self, perf: Dict[str, Any]) -> None:
        log_print("\nPerformance Metrics:")
        log_print(f"  Total Runtime: {perf['total_runtime_minutes']:.2f} minutes")
        log_print(f"  Throughput: {perf['throughput_per_minute']:.2f} items/minute")
        log_print(f"  Avg Duration: {perf['avg_duration_seconds']:.3f} seconds")
        if perf["avg_completed_duration_seconds"] > 0:
            log_print(
                f"  Avg Completed Duration: {perf['avg_completed_duration_seconds']:.3f} seconds"
            )

    def _print_puzzle_metrics(self, puzzle: Dict[str, Any]) -> None:
        if puzzle.get("total_puzzles", 0) <= 0:
            return

        log_print("\nPuzzle Solving Metrics:")
        log_print(f"  Total Puzzles: {puzzle['total_puzzles']}")
        log_print(
            f"  Solved: {puzzle['puzzles_solved']} ({puzzle['puzzle_success_rate_percent']}%)"
        )
        log_print(
            f"  Failed: {puzzle['puzzles_failed']} ({puzzle['puzzle_failure_rate_percent']}%)"
        )
        log_print(f"  Avg Attempts: {puzzle['avg_attempts']:.2f}")

        if puzzle["avg_solved_duration_seconds"] > 0:
            log_print(f"  Avg Solve Time: {puzzle['avg_solved_duration_seconds']:.3f}s")
        if puzzle["avg_failed_duration_seconds"] > 0:
            log_print(
                f"  Avg Failed Time: {puzzle['avg_failed_duration_seconds']:.3f}s"
            )

    def _print_status_breakdown(self, breakdown: Dict[str, Any]) -> None:
        log_print("\nStatus Breakdown:")
        for status, data in breakdown.items():
            log_print(
                f"  {status}: {data['count']} ({data['percentage']}%) - "
                f"avg {data['avg_duration_seconds']:.3f}s"
            )

    def _print_skip_reasons(self, reasons: Dict[str, int]) -> None:
        if not reasons:
            return

        log_print("\nTop Skip Reasons:")
        for reason, count in list(reasons.items())[:5]:
            log_print(f"  {reason}: {count}")

    def _print_error_analysis(self, analysis: Dict[str, Any]) -> None:
        if analysis["total_errors"] <= 0:
            return

        log_print("\nError Analysis:")
        log_print(f"  Total Errors: {analysis['total_errors']}")
        log_print(f"  Unique Error Types: {analysis['unique_error_types']}")
        if analysis["error_frequency"]:
            log_print("  Top Errors:")
            for error, count in list(analysis["error_frequency"].items())[:3]:
                log_print(f"    {error[:80]}...: {count}")
