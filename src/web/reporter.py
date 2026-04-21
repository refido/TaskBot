import json
import traceback
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional

from src.infrastructure.reporting.analytics import MetricsCalculator
from src.infrastructure.reporting.classification import (
    _APPLICATION_ERROR_LABEL,
    _CANNOT_TRANSACT_AT_BASE_REASON,
    _CANNOT_TRANSACT_AT_BASE_SKIP_TYPE,
    _CANNOT_TRANSACT_AT_BASE_STATUS,
    _FAILED_PUZZLE_SOLVE_REASON,
    _FAILED_PUZZLE_SOLVE_STATUS,
    _INVALID_REGISTERED_NIK_REASON,
    _INVALID_REGISTERED_NIK_SKIP_TYPE,
    _INVALID_REGISTERED_NIK_STATUS,
    _NEEDS_UPDATE_REASON,
    _NEEDS_UPDATE_SKIP_TYPE,
    _NEEDS_UPDATE_STATUS,
    _NETWORK_ERROR_LABEL,
    _UNDER_17_REASON,
    _UNDER_17_SKIP_TYPE,
    _UNDER_17_STATUS,
    _UNREGISTERED_SKIP_TYPE,
    _UNREGISTERED_STATUS,
    _UNUSUAL_TRANSACTION_OTHER_BASE_REASON,
    _UNUSUAL_TRANSACTION_OTHER_BASE_SKIP_TYPE,
    _UNUSUAL_TRANSACTION_OTHER_BASE_STATUS,
    classify_error_label,
    is_unregistered_row,
    normalize_error_reason,
    reason_indicates_cannot_transact_at_base,
    reason_indicates_failed_puzzle_solve,
    reason_indicates_invalid_registered_nik,
    reason_indicates_needs_update,
    reason_indicates_under_17,
    reason_indicates_unregistered,
    reason_indicates_unusual_transaction_at_other_base,
)
from src.infrastructure.reporting.console_summary import (
    print_error_analysis,
    print_nik_statistics,
    print_performance,
    print_puzzle_metrics,
    print_section,
    print_skip_reasons,
    print_skipped_niks,
    print_status_breakdown,
    print_unregistered_niks,
)
from src.infrastructure.reporting.file_writer import FileWriter
from src.infrastructure.reporting.models import TransactionRow, now_iso, parse_iso
from src.logging_utils import log_print, logger
from src.path_utils import build_dated_dir, build_timestamped_run_dir

__all__ = [
    "FileWriter",
    "MetricsCalculator",
    "TransactionReporter",
    "TransactionRow",
    "now_iso",
    "parse_iso",
    "_APPLICATION_ERROR_LABEL",
    "_NETWORK_ERROR_LABEL",
]


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
        puzzle_retry_count: int = 0,
        puzzle_retry_process: str = "",
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
            puzzle_retry_count=puzzle_retry_count,
            puzzle_retry_process=puzzle_retry_process,
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
        reason: str = _NEEDS_UPDATE_REASON,
    ) -> None:
        """Record needs update skip."""
        self.skip(nik, started_at, _NEEDS_UPDATE_SKIP_TYPE, url, reason)

    def skip_under_17(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = _UNDER_17_REASON,
    ) -> None:
        """Record under-17 NIK skip."""
        self.skip(nik, started_at, _UNDER_17_SKIP_TYPE, url, reason)

    def skip_invalid_registered_nik(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = _INVALID_REGISTERED_NIK_REASON,
    ) -> None:
        """Record invalid registered-customer NIK skip."""
        self.skip(
            nik, started_at, _INVALID_REGISTERED_NIK_SKIP_TYPE, url, reason
        )

    def skip_cannot_transact_at_base(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = _CANNOT_TRANSACT_AT_BASE_REASON,
    ) -> None:
        """Record base-restriction skip."""
        self.skip(nik, started_at, _CANNOT_TRANSACT_AT_BASE_SKIP_TYPE, url, reason)

    def skip_unusual_transaction_at_other_base(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = _UNUSUAL_TRANSACTION_OTHER_BASE_REASON,
    ) -> None:
        """Record unusual transaction at another base skip."""
        self.skip(
            nik, started_at, _UNUSUAL_TRANSACTION_OTHER_BASE_SKIP_TYPE, url, reason
        )

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
        puzzle_retry_count: int = 0,
        puzzle_retry_process: str = "",
    ) -> None:
        """Record an error."""
        reason = str(exc)
        error_details = traceback.format_exc()
        combined_reason = f"{reason}\n{error_details}"
        if puzzle_solved is False or self._reason_indicates_failed_puzzle_solve(
            combined_reason
        ):
            self.failed_puzzle_solve(
                nik,
                started_at,
                exc=exc,
                url=url,
                puzzle_attempts=puzzle_attempts,
                puzzle_retry_count=puzzle_retry_count,
                puzzle_retry_process=puzzle_retry_process,
            )
            return
        if self._reason_indicates_unregistered(combined_reason):
            status = _UNREGISTERED_STATUS
        elif self._reason_indicates_needs_update(combined_reason):
            status = _NEEDS_UPDATE_STATUS
            reason = _NEEDS_UPDATE_REASON
        elif self._reason_indicates_invalid_registered_nik(combined_reason):
            status = _INVALID_REGISTERED_NIK_STATUS
            reason = _INVALID_REGISTERED_NIK_REASON
        elif self._reason_indicates_unusual_transaction_at_other_base(combined_reason):
            status = _UNUSUAL_TRANSACTION_OTHER_BASE_STATUS
            reason = _UNUSUAL_TRANSACTION_OTHER_BASE_REASON
        elif self._reason_indicates_cannot_transact_at_base(combined_reason):
            status = _CANNOT_TRANSACT_AT_BASE_STATUS
            reason = _CANNOT_TRANSACT_AT_BASE_REASON
        elif self._reason_indicates_under_17(combined_reason):
            status = _UNDER_17_STATUS
            reason = _UNDER_17_REASON
        else:
            status = "error"
        error_label = (
            self._classify_error_label(exc, reason, error_details)
            if status == "error"
            else ""
        )
        row = self._create_row(
            status=status,
            nik=nik,
            started_at=started_at,
            url=url,
            puzzle_solved=puzzle_solved,
            puzzle_attempts=puzzle_attempts,
            puzzle_retry_count=puzzle_retry_count,
            puzzle_retry_process=puzzle_retry_process,
            reason=reason,
            error=error_details,
            error_label=error_label,
        )
        self._record_row(row)

    def failed_puzzle_solve(
        self,
        nik: str,
        started_at: str,
        exc: Optional[Exception] = None,
        url: str = "",
        puzzle_attempts: int = 0,
        puzzle_retry_count: int = 0,
        puzzle_retry_process: str = "",
        reason: str = _FAILED_PUZZLE_SOLVE_REASON,
    ) -> None:
        """Record a failed puzzle solve separately from actual errors."""
        error_details = traceback.format_exc() if exc is not None else ""
        resolved_reason = str(exc).strip() if exc is not None else reason
        self._add_row(
            status=_FAILED_PUZZLE_SOLVE_STATUS,
            nik=nik,
            started_at=started_at,
            url=url,
            puzzle_solved=False,
            puzzle_attempts=puzzle_attempts,
            puzzle_retry_count=puzzle_retry_count,
            puzzle_retry_process=puzzle_retry_process,
            reason=resolved_reason or _FAILED_PUZZLE_SOLVE_REASON,
            error=error_details,
        )

    def write_files(self, run_name: Optional[str] = None) -> None:
        """Write final snapshot files and update operator summary."""
        # NOTE: run_name is kept for backward compatibility; original code did not use it.
        calculator = MetricsCalculator(self.rows)
        mapping_report = self.get_mapping_report()
        mapping_error_report = self.get_mapping_error_report()
        mapping_failed_puzzle_report = self.get_mapping_failed_puzzle_report()
        payload = {
            "operator": self.operator,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": calculator.get_summary(),
            "analytics": calculator.get_analytics(self.run_started_at),
            "items": [asdict(r) for r in self.rows],
            "mapping_report": mapping_report,
            "mapping_error_report": mapping_error_report,
            "mapping_failed_puzzle_report": mapping_failed_puzzle_report,
            "nik_lists": {
                **mapping_report,
                "mapping_error_report": mapping_error_report,
                "mapping_failed_puzzle_report": mapping_failed_puzzle_report,
                "errors_by_label": self.get_error_niks_by_label(),
                "errors_by_reason": self.get_error_niks_by_reason(),
                "other_statuses": self.get_other_status_niks_by_status(),
                "failed_puzzle_solve": self.get_failed_puzzle_solve_niks(),
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
            "failed_puzzle_solve": self.get_failed_puzzle_solve_niks(),
            "successful": self.get_successful_niks(),
            "skipped": self.get_skipped_niks_by_type(),
            "unregistered": self.get_unregistered_niks(),
        }

    def get_mapping_error_report(self) -> Dict[str, List[str]]:
        """Group actual failed NIKs by normalized error reason."""
        grouped: DefaultDict[str, List[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != "error" or self._is_unregistered_row(row):
                continue

            grouped[self._normalize_error_reason(row.reason)].append(row.nik)

        return dict(grouped)

    def get_mapping_failed_puzzle_report(self) -> Dict[str, List[str]]:
        """Group failed puzzle solves by their reporting reason."""
        grouped: DefaultDict[str, List[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != _FAILED_PUZZLE_SOLVE_STATUS:
                continue
            key = row.reason.strip() if row.reason else _FAILED_PUZZLE_SOLVE_REASON
            grouped[key].append(row.nik)

        return dict(grouped)

    def get_error_niks_by_reason(self) -> Dict[str, List[str]]:
        """Get failed NIKs grouped by normalized error reason."""
        grouped: DefaultDict[str, List[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != "error" or self._is_unregistered_row(row):
                continue
            grouped[self._normalize_error_reason(row.reason)].append(row.nik)
        return dict(grouped)

    def get_error_niks_by_label(self) -> Dict[str, List[str]]:
        """Get failed NIKs grouped by error label."""
        grouped: DefaultDict[str, List[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != "error" or self._is_unregistered_row(row):
                continue
            grouped[row.error_label or _APPLICATION_ERROR_LABEL].append(row.nik)
        return dict(grouped)

    def get_other_status_niks_by_status(self) -> Dict[str, List[str]]:
        """Get NIKs grouped by any non-standard status."""
        grouped: DefaultDict[str, List[str]] = defaultdict(list)
        for row in self.rows:
            if row.status in {"completed", "error", _FAILED_PUZZLE_SOLVE_STATUS}:
                continue
            if row.status.startswith("skipped_"):
                continue
            grouped[row.status].append(row.nik)
        return dict(grouped)

    def get_puzzle_failed_niks(self) -> List[str]:
        """Get NIKs where puzzle solving failed."""
        return self.get_failed_puzzle_solve_niks()

    def get_failed_puzzle_solve_niks(self) -> List[str]:
        """Get NIKs where puzzle solving failed."""
        return [r.nik for r in self.rows if r.status == _FAILED_PUZZLE_SOLVE_STATUS]

    def get_puzzle_stats_by_nik(self) -> Dict[str, Dict[str, Any]]:
        """Get puzzle statistics grouped by NIK."""
        nik_stats: DefaultDict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "attempts": 0,
                "solved": False,
                "retry_count": 0,
                "retry_process": "",
            }
        )
        for row in self.rows:
            if row.puzzle_solved is not None:
                nik_stats[row.nik]["attempts"] = row.puzzle_attempts
                nik_stats[row.nik]["solved"] = row.puzzle_solved
                nik_stats[row.nik]["retry_count"] = row.puzzle_retry_count
                nik_stats[row.nik]["retry_process"] = row.puzzle_retry_process
        return dict(nik_stats)

    def get_analytics_with_niks(self) -> Dict[str, Any]:
        """Get comprehensive analytics including NIK lists."""
        base_analytics = self.get_analytics()
        base_analytics["nik_details"] = {
            "mapping_report": self.get_mapping_report(),
            "mapping_error_report": self.get_mapping_error_report(),
            "mapping_failed_puzzle_report": self.get_mapping_failed_puzzle_report(),
            "successful_niks": self.get_successful_niks(),
            "failed_niks": self.get_failed_niks(),
            "failed_puzzle_solve_niks": self.get_failed_puzzle_solve_niks(),
            "skipped_by_type": self.get_skipped_niks_by_type(),
            "unregistered_niks": self.get_unregistered_niks(),
            "errors_by_label": self.get_error_niks_by_label(),
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
            ["success", "failed", "skip", "unregistered"],
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
        return normalize_error_reason(reason)

    @staticmethod
    def _classify_error_label(exc: Exception, reason: str, error_details: str) -> str:
        return classify_error_label(exc, reason, error_details)

    @staticmethod
    def _reason_indicates_unregistered(reason: str) -> bool:
        return reason_indicates_unregistered(reason)

    @staticmethod
    def _reason_indicates_failed_puzzle_solve(reason: str) -> bool:
        return reason_indicates_failed_puzzle_solve(reason)

    @staticmethod
    def _reason_indicates_needs_update(reason: str) -> bool:
        return reason_indicates_needs_update(reason)

    @staticmethod
    def _reason_indicates_under_17(reason: str) -> bool:
        return reason_indicates_under_17(reason)

    @staticmethod
    def _reason_indicates_invalid_registered_nik(reason: str) -> bool:
        return reason_indicates_invalid_registered_nik(reason)

    @staticmethod
    def _reason_indicates_cannot_transact_at_base(reason: str) -> bool:
        return reason_indicates_cannot_transact_at_base(reason)

    @staticmethod
    def _reason_indicates_unusual_transaction_at_other_base(reason: str) -> bool:
        return reason_indicates_unusual_transaction_at_other_base(reason)

    def _is_unregistered_row(self, row: TransactionRow) -> bool:
        return is_unregistered_row(row)

    # Private helpers (data recording)
    def _add_row(
        self,
        status: str,
        nik: str,
        started_at: str,
        url: str = "",
        puzzle_solved: Optional[bool] = None,
        puzzle_attempts: int = 0,
        puzzle_retry_count: int = 0,
        puzzle_retry_process: str = "",
        reason: str = "",
        error: str = "",
        error_label: str = "",
    ) -> None:
        row = self._create_row(
            status=status,
            nik=nik,
            started_at=started_at,
            url=url,
            puzzle_solved=puzzle_solved,
            puzzle_attempts=puzzle_attempts,
            puzzle_retry_count=puzzle_retry_count,
            puzzle_retry_process=puzzle_retry_process,
            reason=reason,
            error=error,
            error_label=error_label,
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
        puzzle_retry_count: int = 0,
        puzzle_retry_process: str = "",
        reason: str = "",
        error: str = "",
        error_label: str = "",
    ) -> TransactionRow:
        row = TransactionRow(
            operator=self.operator,
            nik=nik,
            status=status,
            started_at=started_at or self.run_started_at,
            finished_at=now_iso(),
            url=url,
            error=error,
            error_label=error_label,
            puzzle_solved=puzzle_solved,
            puzzle_attempts=puzzle_attempts,
            puzzle_retry_count=puzzle_retry_count,
            puzzle_retry_process=puzzle_retry_process,
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
            puzzle_retry_count=row.puzzle_retry_count,
            puzzle_retry_process=row.puzzle_retry_process,
            error_label=row.error_label,
            reason=row.reason,
        ).info("Transaction row recorded")

    # Private helpers (meta + operator summary)
    def _write_meta(self) -> None:
        calculator = MetricsCalculator(self.rows)
        mapping_report = self.get_mapping_report()
        mapping_error_report = self.get_mapping_error_report()
        mapping_failed_puzzle_report = self.get_mapping_failed_puzzle_report()
        payload = {
            "operator": self.operator,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": calculator.get_summary(),
            "analytics": calculator.get_analytics(self.run_started_at),
            "mapping_report": mapping_report,
            "mapping_error_report": mapping_error_report,
            "mapping_failed_puzzle_report": mapping_failed_puzzle_report,
            "nik_lists": {
                **mapping_report,
                "mapping_error_report": mapping_error_report,
                "mapping_failed_puzzle_report": mapping_failed_puzzle_report,
                "errors_by_label": self.get_error_niks_by_label(),
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
        print_skipped_niks(self, log_print)

    def _print_unregistered_niks(self) -> None:
        print_unregistered_niks(self, log_print)

    def _print_nik_statistics(self) -> None:
        print_nik_statistics(self, log_print)

    def _print_section(
        self,
        title: str,
        data: Dict[str, Any],
        filters: Optional[List[str]] = None,
        suffix: str = "",
    ) -> None:
        print_section(title, data, log_print, filters=filters, suffix=suffix)

    def _print_performance(self, perf: Dict[str, Any]) -> None:
        print_performance(perf, log_print)

    def _print_puzzle_metrics(self, puzzle: Dict[str, Any]) -> None:
        print_puzzle_metrics(puzzle, log_print)

    def _print_status_breakdown(self, breakdown: Dict[str, Any]) -> None:
        print_status_breakdown(breakdown, log_print)

    def _print_skip_reasons(self, reasons: Dict[str, int]) -> None:
        print_skip_reasons(reasons, log_print)

    def _print_error_analysis(self, analysis: Dict[str, Any]) -> None:
        print_error_analysis(analysis, log_print)
