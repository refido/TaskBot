from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import ClassVar

from src.infrastructure.reporting.models import TransactionRow
from src.privacy import (
    display_nik,
    public_operator,
    sanitize_public_value,
    sanitize_text,
)


class FileWriter:
    """Handles file I/O operations for transaction data."""

    _CSV_FIELDNAMES: ClassVar[list[str]] = [
        "run_id",
        "operator_id",
        "operator",
        "nik",
        "status",
        "started_at",
        "finished_at",
        "duration_seconds",
        "puzzle_solved",
        "puzzle_attempts",
        "puzzle_retry_count",
        "puzzle_retry_process",
        "url",
        "error",
        "error_label",
        "reason",
    ]

    def __init__(self, csv_path: Path, jsonl_path: Path):
        self.csv_path = csv_path
        self.jsonl_path = jsonl_path
        self.fieldnames = list(self._CSV_FIELDNAMES)

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
            json.dumps(
                sanitize_public_value(data),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _append_to_csv(self, row: TransactionRow) -> None:
        with self.csv_path.open("a", newline="", encoding="utf-8") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=self.fieldnames)
            writer.writerow(self.public_row_payload(row))
            self._flush_file(file_handle)

    def _append_to_jsonl(self, row: TransactionRow) -> None:
        with self.jsonl_path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(
                json.dumps(self.public_row_payload(row), ensure_ascii=False) + "\n"
            )
            self._flush_file(file_handle)

    @staticmethod
    def _flush_file(file_handle) -> None:
        """Flush and sync file to disk."""
        file_handle.flush()
        try:
            os.fsync(file_handle.fileno())
        except OSError:
            # Best-effort fsync; preserve original behavior.
            pass

    @staticmethod
    def public_row_payload(row: TransactionRow) -> dict:
        payload = asdict(row)
        payload["operator_id"] = public_operator(payload["operator_id"])
        payload["operator"] = public_operator(payload["operator"])
        payload["nik"] = display_nik(payload["nik"])
        payload["url"] = sanitize_text(payload["url"])
        payload["reason"] = sanitize_text(payload["reason"])
        payload["error"] = sanitize_text(payload["error"])
        return payload
