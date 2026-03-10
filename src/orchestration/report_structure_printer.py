import json
from pathlib import Path
from typing import Any, Dict

from src.logging_utils import log_print
from src.web.reporter import TransactionReporter


class ReportStructurePrinter:
    """Prints report folder structure for an operator."""

    def __init__(self, reports_root: Path = Path("reports")) -> None:
        self.reports_root = reports_root

    def print_for_operator(self, email_user: str) -> None:
        safe_operator = TransactionReporter._sanitize_folder_name(email_user)
        operator_dir = self.reports_root / safe_operator

        if not operator_dir.exists():
            log_print(f"No reports found for operator: {email_user}")
            return

        log_print(f"\nReport Structure for {email_user}:")
        log_print(f"{'=' * 60}")
        log_print(f"Root: {operator_dir}")

        date_folders = sorted([d for d in operator_dir.iterdir() if d.is_dir()])

        for date_folder in date_folders:
            if date_folder.name == "operator_summary.json":
                continue

            log_print(f"\n  {date_folder.name}/")

            run_folders = sorted([r for r in date_folder.iterdir() if r.is_dir()])
            for run_folder in run_folders:
                log_print(f"    {run_folder.name}/")

                key_files = ["items.csv", "analytics.json", "run_meta.json"]
                for file_name in key_files:
                    file_path = run_folder / file_name
                    if file_path.exists():
                        size = file_path.stat().st_size
                        log_print(f"      {file_name} ({size:,} bytes)")

        self._print_operator_summary(operator_dir)
        log_print(f"{'=' * 60}\n")

    def _print_operator_summary(self, operator_dir: Path) -> None:
        summary_path = operator_dir / "operator_summary.json"
        if not summary_path.exists():
            return

        log_print("\n  operator_summary.json")
        try:
            with summary_path.open("r", encoding="utf-8") as file_handle:
                summary: Dict[str, Any] = json.load(file_handle)
                log_print(f"     Total Runs: {summary['total_runs']}")
                log_print(
                    f"     Completed: {summary['aggregated_stats']['total_completed']}"
                )
                log_print(
                    f"     Success Rate: {summary['aggregated_stats']['success_rate_percent']}%"
                )
        except Exception as exc:
            log_print(f"     Error reading summary: {exc}")


def print_report_structure(email_user: str) -> None:
    """
    Print the report folder structure for an operator.

    Args:
        email_user: Operator email to check
    """
    ReportStructurePrinter().print_for_operator(email_user)
