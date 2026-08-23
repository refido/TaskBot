import json
import os
import re
import traceback
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

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
    print_retry_report,
    print_section,
    print_skip_reasons,
    print_skipped_niks,
    print_status_breakdown,
    print_unregistered_niks,
    print_workflow_summary,
)
from src.infrastructure.reporting.file_writer import FileWriter
from src.infrastructure.reporting.models import (
    RetryEvent,
    TransactionRow,
    WorkflowEvent,
    now_iso,
    parse_iso,
)
from src.logging_utils import log_print, logger
from src.path_utils import build_dated_dir
from src.privacy import display_nik, sanitize_text

BatchSyncCallback = Callable[[tuple[TransactionRow, ...]], None]
_SAFE_OPERATOR_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

__all__ = [
    "_APPLICATION_ERROR_LABEL",
    "_NETWORK_ERROR_LABEL",
    "FileWriter",
    "MetricsCalculator",
    "RetryEvent",
    "TransactionReporter",
    "TransactionRow",
    "WorkflowEvent",
    "now_iso",
    "parse_iso",
]


class TransactionReporter:
    """Main reporter class for managing transaction logging and analytics."""

    def __init__(
        self,
        out_dir: str = "reports",
        run_name: str | None = None,
        per_run_subdir: bool = True,
        operator: str | None = None,
        operator_id: str | None = None,
        run_context: Any | None = None,
    ):
        self.operator_id = self._resolve_operator_id(operator_id, operator)
        # ``operator`` remains a compatibility alias, but never stores credentials.
        self.operator = self.operator_id
        self.run_context = run_context
        self.run_id = str(getattr(run_context, "run_id", "") or run_name or "")
        self.run_started_at = str(
            getattr(run_context, "started_at", "") or now_iso()
        )
        self.rows: list[TransactionRow] = []
        self.retry_events: list[RetryEvent] = []
        self.workflow_events: list[WorkflowEvent] = []
        self._batch_size: int | None = None
        self._batch_sync_callback: BatchSyncCallback | None = None
        self._pending_batch_rows: list[TransactionRow] = []
        self._batch_sync_failed = False

        self._setup_directories(out_dir, run_name, per_run_subdir)

        self.file_writer = FileWriter(self.csv_path, self.jsonl_path)
        self.file_writer.init_csv()

        if not self.jsonl_path.exists():
            self.jsonl_path.touch()
        if not self.workflow_events_path.exists():
            self.workflow_events_path.touch()
        if not self.retries_path.exists():
            self.retries_path.touch()

        self._write_meta()

    # Public methods (external API)
    def start_item(self, nik: str) -> str:
        """Start timing for a new item."""
        return now_iso()

    def configure_batch_sync(
        self,
        sync_callback: BatchSyncCallback,
        *,
        batch_size: int,
    ) -> None:
        """Synchronize each completed batch without coupling reporting to storage."""
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero.")

        self._batch_size = batch_size
        self._batch_sync_callback = sync_callback
        self._sync_complete_batches()

    def flush_pending_batches(self) -> None:
        """Synchronize all unsent terminal rows, including a final partial batch."""
        sync_callback = self._batch_sync_callback
        batch_size = self._batch_size
        if sync_callback is None or batch_size is None:
            return

        while self._pending_batch_rows:
            batch = tuple(self._pending_batch_rows[:batch_size])
            sync_callback(batch)
            del self._pending_batch_rows[: len(batch)]

        self._batch_sync_failed = False

    def complete(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        puzzle_solved: bool | None = None,
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
        self.skip(nik, started_at, _INVALID_REGISTERED_NIK_SKIP_TYPE, url, reason)

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
        puzzle_solved: bool | None = None,
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
        exc: Exception | None = None,
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

    def record_retry(
        self,
        nik: str,
        *,
        process: str,
        trigger: str,
        attempt_number: int,
        retry_number: int,
        max_retries: int,
        exc: Exception | None = None,
        url: str = "",
    ) -> None:
        """Record retry telemetry without adding another transaction row."""
        reason = str(exc).strip() if exc is not None else ""
        error_details = traceback.format_exc() if exc is not None else ""
        error_label = (
            self._classify_error_label(exc, reason, error_details)
            if exc is not None
            else ""
        )
        event = RetryEvent(
            operator=self.operator,
            operator_id=self.operator_id,
            run_id=self.run_id,
            nik=display_nik(nik),
            process=process,
            trigger=trigger,
            attempt_number=attempt_number,
            retry_number=retry_number,
            max_retries=max_retries,
            recorded_at=now_iso(),
            url=sanitize_text(url),
            reason=sanitize_text(reason),
            error_label=error_label,
        )
        self._get_retry_events().append(event)
        self._append_jsonl(self.retries_path, asdict(event))
        self._write_meta()
        logger.bind(
            event="report.retry_recorded",
            operator_id=self.operator_id,
            nik=nik,
            process=process,
            trigger=trigger,
            attempt_number=attempt_number,
            retry_number=retry_number,
            max_retries=max_retries,
            error_label=error_label,
            reason=reason,
        ).info("Transaction retry recorded")

    def record_workflow_event(
        self,
        nik: str,
        *,
        event: str,
        stage: str = "",
        url: str = "",
        reason: str = "",
    ) -> None:
        """Append one business milestone without creating a terminal row."""
        workflow_event = WorkflowEvent(
            operator=self.operator_id,
            operator_id=self.operator_id,
            run_id=self.run_id,
            nik=display_nik(nik),
            event=event,
            recorded_at=now_iso(),
            stage=stage,
            url=sanitize_text(url),
            reason=sanitize_text(reason),
        )
        self.workflow_events.append(workflow_event)
        self._append_jsonl(self.workflow_events_path, asdict(workflow_event))
        logger.bind(
            event=f"customer.workflow.{event}",
            operator_id=self.operator_id,
            nik=nik,
            stage=stage,
            reason=reason,
        ).info("Customer workflow milestone recorded")

    def get_workflow_event_report(self) -> dict[str, Any]:
        by_name: defaultdict[str, list[str]] = defaultdict(list)
        for workflow_event in self.workflow_events:
            self._append_unique(by_name[workflow_event.event], workflow_event.nik)
        return {
            "total_events": len(self.workflow_events),
            "consent_niks": len(by_name["consent_detected"]),
            "update_required_niks": len(by_name["customer_update_required"]),
            "updated_niks": len(by_name["customer_update_success"]),
            "same_nik_restarts": len(by_name["same_nik_restart_after_update"]),
            "update_failures": len(by_name["customer_update_failed"]),
            "repeated_update_requests": len(by_name["customer_update_required_again"]),
            "updated_nik_values": by_name["customer_update_success"],
            "consent_nik_values": by_name["consent_detected"],
            "update_failed_nik_values": by_name["customer_update_failed"],
        }

    def write_files(self, run_name: str | None = None) -> None:
        """Write final snapshot files and update operator summary."""
        # NOTE: run_name is kept for backward compatibility; original code did not use it.
        calculator = MetricsCalculator(self.rows)
        mapping_report = self.get_mapping_report()
        mapping_error_report = self.get_mapping_error_report()
        mapping_failed_puzzle_report = self.get_mapping_failed_puzzle_report()
        retry_report = {
            **self._compact_retry_report(),
            "operator": self.operator_id,
            "operator_id": self.operator_id,
            "run_id": self.run_id,
        }
        workflow_summary = self.get_workflow_event_report()
        payload = {
            "run_id": self.run_id,
            "operator": self.operator_id,
            "operator_id": self.operator_id,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": calculator.get_summary(),
            "analytics": calculator.get_analytics(self.run_started_at),
            "retry_report": retry_report,
            "workflow_summary": workflow_summary,
            "items": [self.file_writer.public_row_payload(r) for r in self.rows],
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
                "retried": retry_report["retried_niks"],
            },
            "puzzle_stats_by_nik": self.get_puzzle_stats_by_nik(),
        }

        self.file_writer.write_json(self.final_json_path, payload)
        self.file_writer.write_json(
            self.analytics_path,
            {
                "run_id": self.run_id,
                "operator_id": self.operator_id,
                **calculator.get_analytics(self.run_started_at),
            },
        )

        self._write_meta()
        logger.bind(
            event="report.files_written",
            operator_id=self.operator_id,
            run_id=self.run_id,
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

    def summary(self) -> dict[str, int]:
        """Get summary counts."""
        return MetricsCalculator(self.rows).get_summary()

    def get_analytics(self) -> dict[str, Any]:
        """Get comprehensive analytics."""
        return MetricsCalculator(self.rows).get_analytics(self.run_started_at)

    def get_rows_by_status(self, status: str) -> list[TransactionRow]:
        """Filter rows by status."""
        return [r for r in self.rows if r.status == status]

    def get_failed_niks(self) -> list[str]:
        """Get list of failed NIKs (error rows only)."""
        return [
            display_nik(r.nik)
            for r in self.rows
            if r.status == "error" and not self._is_unregistered_row(r)
        ]

    def get_successful_niks(self) -> list[str]:
        """Get list of successful NIKs."""
        return [display_nik(r.nik) for r in self.rows if r.status == "completed"]

    def get_skipped_niks_by_type(
        self, include_unregistered: bool = False
    ) -> dict[str, list[str]]:
        """Get skipped NIKs grouped by skip type."""
        skipped_by_type: defaultdict[str, list[str]] = defaultdict(list)
        for row in self.rows:
            if row.status.startswith("skipped_"):
                skip_type = row.status.replace("skipped_", "")
                if skip_type == _UNREGISTERED_SKIP_TYPE and not include_unregistered:
                    continue
                skipped_by_type[skip_type].append(display_nik(row.nik))
        return dict(skipped_by_type)

    def get_unregistered_niks(self) -> list[str]:
        """Get NIKs flagged as 'Pelanggan Tidak Terdaftar'."""
        return [display_nik(r.nik) for r in self.rows if self._is_unregistered_row(r)]

    def get_mapping_report(self) -> dict[str, Any]:
        """Build the main mapping report buckets for the current run."""
        return {
            "failed": self.get_failed_niks(),
            "failed_puzzle_solve": self.get_failed_puzzle_solve_niks(),
            "successful": self.get_successful_niks(),
            "skipped": self.get_skipped_niks_by_type(),
            "unregistered": self.get_unregistered_niks(),
        }

    def get_mapping_error_report(self) -> dict[str, list[str]]:
        """Group actual failed NIKs by normalized error reason."""
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != "error" or self._is_unregistered_row(row):
                continue

            grouped[self._normalize_error_reason(row.reason)].append(
                display_nik(row.nik)
            )

        return dict(grouped)

    def get_mapping_failed_puzzle_report(self) -> dict[str, list[str]]:
        """Group failed puzzle solves by their reporting reason."""
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != _FAILED_PUZZLE_SOLVE_STATUS:
                continue
            key = row.reason.strip() if row.reason else _FAILED_PUZZLE_SOLVE_REASON
            grouped[key].append(display_nik(row.nik))

        return dict(grouped)

    def get_retry_report(self) -> dict[str, Any]:
        """Build retry telemetry for the current operator run."""
        events = self._get_retry_events()
        retried_niks: list[str] = []
        by_process: defaultdict[str, list[str]] = defaultdict(list)
        by_trigger: defaultdict[str, list[str]] = defaultdict(list)

        for event in events:
            self._append_unique(retried_niks, event.nik)
            self._append_unique(by_process[event.process], event.nik)
            self._append_unique(by_trigger[event.trigger], event.nik)

        return {
            "operator": self.operator,
            "operator_id": self.operator_id,
            "run_id": self.run_id,
            "run_started_at": self.run_started_at,
            "total_retry_events": len(events),
            "total_retried_niks": len(retried_niks),
            "retried_niks": retried_niks,
            "by_process": dict(by_process),
            "by_trigger": dict(by_trigger),
            "events": [asdict(event) for event in events],
        }

    def _compact_retry_report(self) -> dict[str, Any]:
        """Keep event history in retries.jsonl, not duplicated in summaries."""
        report = self.get_retry_report()
        report.pop("events", None)
        return report

    def get_error_niks_by_reason(self) -> dict[str, list[str]]:
        """Get failed NIKs grouped by normalized error reason."""
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != "error" or self._is_unregistered_row(row):
                continue
            grouped[self._normalize_error_reason(row.reason)].append(
                display_nik(row.nik)
            )
        return dict(grouped)

    def get_error_niks_by_label(self) -> dict[str, list[str]]:
        """Get failed NIKs grouped by error label."""
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for row in self.rows:
            if row.status != "error" or self._is_unregistered_row(row):
                continue
            grouped[row.error_label or _APPLICATION_ERROR_LABEL].append(
                display_nik(row.nik)
            )
        return dict(grouped)

    def get_other_status_niks_by_status(self) -> dict[str, list[str]]:
        """Get NIKs grouped by any non-standard status."""
        grouped: defaultdict[str, list[str]] = defaultdict(list)
        for row in self.rows:
            if row.status in {"completed", "error", _FAILED_PUZZLE_SOLVE_STATUS}:
                continue
            if row.status.startswith("skipped_"):
                continue
            grouped[row.status].append(display_nik(row.nik))
        return dict(grouped)

    def get_puzzle_failed_niks(self) -> list[str]:
        """Get NIKs where puzzle solving failed."""
        return self.get_failed_puzzle_solve_niks()

    def get_failed_puzzle_solve_niks(self) -> list[str]:
        """Get NIKs where puzzle solving failed."""
        return [
            display_nik(r.nik)
            for r in self.rows
            if r.status == _FAILED_PUZZLE_SOLVE_STATUS
        ]

    def get_puzzle_stats_by_nik(self) -> dict[str, dict[str, Any]]:
        """Get puzzle statistics grouped by NIK."""
        nik_stats: defaultdict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "attempts": 0,
                "solved": False,
                "retry_count": 0,
                "retry_process": "",
            }
        )
        for row in self.rows:
            if row.puzzle_solved is not None:
                public_nik = display_nik(row.nik)
                nik_stats[public_nik]["attempts"] = row.puzzle_attempts
                nik_stats[public_nik]["solved"] = row.puzzle_solved
                nik_stats[public_nik]["retry_count"] = row.puzzle_retry_count
                nik_stats[public_nik]["retry_process"] = row.puzzle_retry_process
        return dict(nik_stats)

    def get_analytics_with_niks(self) -> dict[str, Any]:
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
            "retry_report": self.get_retry_report(),
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
        self._print_retry_report()
        print_workflow_summary(self, log_print)
        self._print_nik_statistics()

        log_print("\n" + "=" * 60)
        log_print(f"Analytics saved to: {self.analytics_path}")
        log_print("=" * 60 + "\n")

    # Protected-ish methods (kept private to preserve current design)
    def _setup_directories(
        self, out_dir: str, run_name: str | None, per_run_subdir: bool
    ) -> None:
        """Place this operator beneath the one application execution directory."""
        now_local = datetime.now().astimezone()
        safe_operator = self._sanitize_folder_name(self.operator_id)
        context_run_dir = getattr(self.run_context, "run_dir", None)
        if context_run_dir is not None:
            self.application_run_dir = Path(context_run_dir)
            if not self.run_id:
                self.run_id = self.application_run_dir.name
        else:
            if not self.run_id:
                self.run_id = (
                    f"{now_local:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:4]}"
                )
            report_root = Path(out_dir)
            self.application_run_dir = (
                build_dated_dir(report_root, now_local)
                / self._sanitize_folder_name(self.run_id)
            )

        self.operator_dir = self.application_run_dir / "operators" / safe_operator
        self.base_dir = self.operator_dir
        self.run_dir = self.operator_dir

        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.csv_path = self.run_dir / "items.csv"
        self.jsonl_path = self.run_dir / "items.jsonl"
        self.meta_path = self.run_dir / "summary.json"
        self.final_json_path = self.run_dir / "items_snapshot.json"
        self.analytics_path = self.run_dir / "analytics.json"
        self.workflow_events_path = self.run_dir / "workflow_events.jsonl"
        self.retries_path = self.run_dir / "retries.jsonl"

        self.operator_summary_path = self.meta_path

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
    def _resolve_operator_id(
        operator_id: str | None,
        legacy_operator: str | None,
    ) -> str:
        """Accept only non-secret IDs and safely handle legacy email callers."""
        if operator_id is not None:
            candidate = operator_id.strip()
            if _SAFE_OPERATOR_ID_PATTERN.fullmatch(candidate) is None:
                raise ValueError(
                    "operator_id must be a non-secret identifier containing only "
                    "letters, numbers, underscores, or hyphens."
                )
            return candidate

        candidate = (legacy_operator or "").strip()
        if _SAFE_OPERATOR_ID_PATTERN.fullmatch(candidate) is not None:
            return candidate

        # Historical callers supplied the login email as ``operator``.  It cannot
        # be reused, masked, or hashed as identity, so use the stable first-account
        # compatibility ID. Production multi-account callers pass operator_id.
        return "operator_01"

    @staticmethod
    def _normalize_error_reason(reason: str) -> str:
        return normalize_error_reason(reason)

    def _get_retry_events(self) -> list[RetryEvent]:
        retry_events = getattr(self, "retry_events", None)
        if retry_events is None:
            retry_events = []
            self.retry_events = retry_events
        return retry_events

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)

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
        puzzle_solved: bool | None = None,
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
        puzzle_solved: bool | None = None,
        puzzle_attempts: int = 0,
        puzzle_retry_count: int = 0,
        puzzle_retry_process: str = "",
        reason: str = "",
        error: str = "",
        error_label: str = "",
    ) -> TransactionRow:
        row = TransactionRow(
            operator=self.operator,
            operator_id=self.operator_id,
            run_id=self.run_id,
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
            operator_id=self.operator_id,
            run_id=self.run_id,
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
        self._queue_row_for_batch_sync(row)

    def _queue_row_for_batch_sync(self, row: TransactionRow) -> None:
        if self._batch_sync_callback is None:
            return

        self._pending_batch_rows.append(row)
        self._sync_complete_batches()

    def _sync_complete_batches(self) -> None:
        sync_callback = self._batch_sync_callback
        batch_size = self._batch_size
        if sync_callback is None or batch_size is None or self._batch_sync_failed:
            return

        while len(self._pending_batch_rows) >= batch_size:
            batch = tuple(self._pending_batch_rows[:batch_size])
            try:
                sync_callback(batch)
            except Exception:  # noqa: BLE001 - database callback errors are retried at finalization.
                self._batch_sync_failed = True
                logger.bind(
                    event="report.batch_sync.deferred",
                    operator_id=self.operator_id,
                    run_id=self.run_id,
                    batch_size=len(batch),
                    pending_row_count=len(self._pending_batch_rows),
                ).exception("Report batch sync failed; retrying during finalization")
                return
            del self._pending_batch_rows[:batch_size]

    # Private helpers (meta + operator summary)
    def _write_meta(self) -> None:
        calculator = MetricsCalculator(self.rows)
        mapping_report = self.get_mapping_report()
        mapping_error_report = self.get_mapping_error_report()
        mapping_failed_puzzle_report = self.get_mapping_failed_puzzle_report()
        retry_report = {
            **self._compact_retry_report(),
            "operator": self.operator_id,
            "operator_id": self.operator_id,
            "run_id": self.run_id,
        }
        counts = calculator.get_summary()
        workflow_summary = self.get_workflow_event_report()
        ended_at = now_iso()
        skipped = sum(
            count for key, count in counts.items() if key.startswith("skipped_")
        )
        failed = counts.get("error", 0) + counts.get(
            _FAILED_PUZZLE_SOLVE_STATUS, 0
        )
        payload = {
            "run_id": self.run_id,
            "operator": self.operator_id,
            "operator_id": self.operator_id,
            "started_at": self.run_started_at,
            "ended_at": ended_at,
            "total_niks": len(self.rows),
            "completed": counts.get("completed", 0),
            "skipped": skipped,
            "failed": failed,
            "customer_updates": workflow_summary["updated_niks"],
            "consent_encounters": workflow_summary["consent_niks"],
            "retries": retry_report["total_retry_events"],
            "run_started_at": self.run_started_at,
            "run_ended_at": ended_at,
            "counts": counts,
            "analytics": calculator.get_analytics(self.run_started_at),
            "retry_report": retry_report,
            "workflow_summary": workflow_summary,
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
                "retried": retry_report["retried_niks"],
            },
            "files": {
                "csv": str(self.csv_path),
                "jsonl": str(self.jsonl_path),
                "final_snapshot": str(self.final_json_path),
                "analytics": str(self.analytics_path),
                "workflow_events": str(self.workflow_events_path),
                "retries": str(self.retries_path),
            },
            "paths": {
                "application_run_dir": str(self.application_run_dir),
                "run_dir": str(self.run_dir),
            },
        }
        self.file_writer.write_json(self.meta_path, payload)
        logger.bind(
            event="report.meta_written",
            operator_id=self.operator_id,
            run_id=self.run_id,
            run_dir=str(self.run_dir),
            counts=payload["counts"],
            meta_path=str(self.meta_path),
        ).debug("Run meta updated")

    def _write_operator_summary(self) -> None:
        """Compatibility wrapper for the current-run operator summary."""
        self._write_meta()

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            file_handle.flush()
            try:
                os.fsync(file_handle.fileno())
            except OSError:
                pass

    def _try_read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as file_handle:
                return json.load(file_handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.bind(
                event="report.json_read_error",
                operator_id=self.operator_id,
                run_id=self.run_id,
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

    def _print_retry_report(self) -> None:
        print_retry_report(self, log_print)

    def _print_section(
        self,
        title: str,
        data: dict[str, Any],
        filters: list[str] | None = None,
        suffix: str = "",
    ) -> None:
        print_section(title, data, log_print, filters=filters, suffix=suffix)

    def _print_performance(self, perf: dict[str, Any]) -> None:
        print_performance(perf, log_print)

    def _print_puzzle_metrics(self, puzzle: dict[str, Any]) -> None:
        print_puzzle_metrics(puzzle, log_print)

    def _print_status_breakdown(self, breakdown: dict[str, Any]) -> None:
        print_status_breakdown(breakdown, log_print)

    def _print_skip_reasons(self, reasons: dict[str, int]) -> None:
        print_skip_reasons(reasons, log_print)

    def _print_error_analysis(self, analysis: dict[str, Any]) -> None:
        print_error_analysis(analysis, log_print)
