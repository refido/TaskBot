"""Compose metadata from resolved values, without owning reporting state or I/O."""

from typing import Any


def build_metadata_payload(
    *,
    run_id: str,
    operator_id: str,
    run_started_at: str,
    ended_at: str,
    total_niks: int,
    completed: int,
    skipped: int,
    failed: int,
    customer_updates: int,
    consent_encounters: int,
    retries: int,
    counts: dict[str, int],
    analytics: dict[str, Any],
    retry_report: dict[str, Any],
    workflow_summary: dict[str, Any],
    nik_parsing_failures: dict[str, Any],
    mapping_report: dict[str, Any],
    mapping_error_report: dict[str, list[str]],
    mapping_failed_puzzle_report: dict[str, list[str]],
    errors_by_label: dict[str, list[str]],
    other_statuses: dict[str, list[str]],
    retried_niks: list[str],
    files: dict[str, str],
    paths: dict[str, str],
) -> dict[str, Any]:
    """Assemble the existing schema, retaining supplied section references.

    Reporter resolves summary scalars before analytics and fallback queries, so
    their error precedence stays outside this builder. Paths are already strings;
    privacy projection, time reads and cache decisions also remain with callers.
    """
    return {
        "run_id": run_id,
        "operator": operator_id,
        "operator_id": operator_id,
        "started_at": run_started_at,
        "ended_at": ended_at,
        "total_niks": total_niks,
        "completed": completed,
        "skipped": skipped,
        "failed": failed,
        "customer_updates": customer_updates,
        "consent_encounters": consent_encounters,
        "retries": retries,
        "run_started_at": run_started_at,
        "run_ended_at": ended_at,
        "counts": counts,
        "analytics": analytics,
        "retry_report": retry_report,
        "workflow_summary": workflow_summary,
        "nik_parsing_failures": nik_parsing_failures,
        "mapping_report": mapping_report,
        "mapping_error_report": mapping_error_report,
        "mapping_failed_puzzle_report": mapping_failed_puzzle_report,
        "nik_lists": {
            **mapping_report,
            "mapping_error_report": mapping_error_report,
            "mapping_failed_puzzle_report": mapping_failed_puzzle_report,
            "errors_by_label": errors_by_label,
            "errors_by_reason": mapping_error_report,
            "other_statuses": other_statuses,
            "retried": retried_niks,
        },
        "files": files,
        "paths": paths,
    }
