from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Callable
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
        "nama_pengguna",
        "jenis_pengguna",
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
        self._damaged_files: set[Path] = set()

    def init_csv(self) -> None:
        """Initialize CSV file with headers if needed."""
        needs_header = not (self.csv_path.exists() and self.csv_path.stat().st_size > 0)
        with self.csv_path.open("a", newline="", encoding="utf-8") as file_handle:
            writer = csv.DictWriter(file_handle, fieldnames=self.fieldnames)
            if needs_header:
                writer.writeheader()
                self._flush_file(file_handle, require_sync=False)

    def append_row(self, row: TransactionRow) -> None:
        """Append a row to both CSV and JSONL files."""
        self._append_with_retry(self.csv_path, self._append_to_csv, row)
        self._append_with_retry(self.jsonl_path, self._append_to_jsonl, row)

    def _append_with_retry(
        self, path: Path, append: Callable[[TransactionRow], None], row: TransactionRow
    ) -> None:
        if path in self._damaged_files:
            raise OSError(f"Unresolved partial write in {path.name}")
        try:
            before = path.stat()
        except FileNotFoundError:
            before = None

        for attempt in range(2):
            try:
                append(row)
                return
            except OSError:
                try:
                    if self._finish_partial_row(path, before, row):
                        return
                except OSError:
                    # Another row must never be appended to an uncertain tail.
                    self._damaged_files.add(path)
                    raise
                if attempt:
                    raise

    def _finish_partial_row(
        self, path: Path, before: os.stat_result | None, row: TransactionRow
    ) -> bool:
        """Return False if no bytes were written. Complete only a matching row."""
        try:
            flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_BINARY", 0)
            stream = os.fdopen(os.open(path, flags), "a+b")
        except FileNotFoundError:
            if before is None:
                return False
            raise
        with stream:
            offset = before.st_size if before else 0
            if before and not os.path.samestat(before, os.fstat(stream.fileno())):
                raise OSError(f"{path.name} was replaced during append")
            length = stream.seek(0, os.SEEK_END) - offset
            if length == 0:
                return False
            is_csv = path == self.csv_path
            buffer = io.StringIO(newline="" if is_csv else os.linesep)
            writer = self._write_csv_row if is_csv else self._write_jsonl_row
            writer(buffer, row)
            expected = buffer.getvalue().encode("utf-8")
            stream.seek(offset)
            if not 0 < length <= len(expected) or stream.read(length) != expected[:length]:
                raise OSError(f"{path.name} has unexpected bytes after the last complete row")
            if stream.seek(0, os.SEEK_END) != offset + length:
                raise OSError(f"{path.name} changed during recovery")
            if length < len(expected):
                stream.write(expected[length:])
            stream.flush()
            os.fsync(stream.fileno())
            return True

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
            self._write_csv_row(file_handle, row)
            self._flush_file(file_handle)

    def _append_to_jsonl(self, row: TransactionRow) -> None:
        with self.jsonl_path.open("a", encoding="utf-8") as file_handle:
            self._write_jsonl_row(file_handle, row)
            self._flush_file(file_handle)

    def _write_csv_row(self, stream, row: TransactionRow) -> None:
        csv.DictWriter(stream, fieldnames=self.fieldnames).writerow(self.public_row_payload(row))

    def _write_jsonl_row(self, stream, row: TransactionRow) -> None:
        stream.write(json.dumps(self.public_row_payload(row), ensure_ascii=False) + "\n")

    @staticmethod
    def _flush_file(file_handle, *, require_sync: bool = True) -> None:
        """Flush and sync file to disk."""
        file_handle.flush()
        try:
            os.fsync(file_handle.fileno())
        except OSError:
            if require_sync:
                raise

    @staticmethod
    def public_row_payload(row: TransactionRow) -> dict:
        raw_payload = asdict(row)
        payload = {
            key: value
            for key, value in raw_payload.items()
            if key not in {"nama_pengguna", "jenis_pengguna"}
        }
        nik_position = list(payload).index("nik") + 1
        ordered_items = list(payload.items())
        ordered_items[nik_position:nik_position] = [
            ("nama_pengguna", raw_payload["nama_pengguna"]),
            ("jenis_pengguna", raw_payload["jenis_pengguna"]),
        ]
        payload = dict(ordered_items)
        payload["operator_id"] = public_operator(payload["operator_id"])
        payload["operator"] = public_operator(payload["operator"])
        payload["nik"] = display_nik(payload["nik"])
        payload["nama_pengguna"] = sanitize_text(payload["nama_pengguna"])
        payload["jenis_pengguna"] = sanitize_text(payload["jenis_pengguna"])
        payload["url"] = sanitize_text(payload["url"])
        payload["reason"] = sanitize_text(payload["reason"])
        payload["error"] = sanitize_text(payload["error"])
        return payload
