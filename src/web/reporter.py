import csv
import json
import os
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class TransactionRow:
    nik: str
    status: str  # completed | skipped_max_kuota | skipped_needs_update | skipped_not_registered | error
    reason: str = ""
    started_at: str = ""
    finished_at: str = ""
    url: str = ""
    error: str = ""
    operator: str = ""


class TransactionReporter:
    def __init__(
        self,
        out_dir: str = "reports",
        run_name: str | None = None,
        per_run_subdir: bool = True,
        operator: str | None = None,
    ):
        self.operator = operator
        # Time stamps for foldering and filenames
        self.run_started_at = now_iso()
        self.run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.day_stamp = datetime.now().strftime("%Y-%m-%d")

        # Folders: reports/YYYY-MM-DD/HHMMSS (or only day folder if per_run_subdir=False)
        self.base_dir = Path(out_dir) / self.day_stamp
        self.run_dir = (
            self.base_dir / (run_name or self.run_stamp)
            if per_run_subdir
            else self.base_dir
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.csv_path = self.run_dir / "items.csv"
        self.jsonl_path = self.run_dir / "items.jsonl"
        self.meta_path = self.run_dir / "run_meta.json"
        self.final_json_path = (
            self.run_dir / "items_snapshot.json"
        )  # optional end-of-run snapshot

        # In-memory rows (still kept for summary and final snapshot)
        self.rows: list[TransactionRow] = []

        # CSV header
        self._fieldnames = [
            "operator",
            "nik",
            "status",
            "reason",
            "started_at",
            "finished_at",
            "url",
            "error",
        ]

        # Initialize CSV (write header once if file is empty/new)
        self._init_csv()

        # Initialize empty jsonl/meta files if not present
        if not self.jsonl_path.exists():
            self.jsonl_path.touch()
        self._write_meta()  # initial meta

    def start_item(self, nik: str) -> str:
        return now_iso()

    def complete(self, nik: str, started_at: str, url: str = "", reason: str = ""):
        self._add(nik, "completed", started_at, url=url, reason=reason)

    def skip_max_kuota(
        self, nik: str, started_at: str, url: str = "", reason: str = "Max kuota alert"
    ):
        self._add(nik, "skipped_max_kuota", started_at, url=url, reason=reason)

    def skip_needs_update(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = "Needs data update",
    ):
        self._add(nik, "skipped_needs_update", started_at, url=url, reason=reason)

    def skip_not_registered(
        self, nik: str, started_at: str, url: str = "", reason: str = "Not registered"
    ):
        self._add(nik, "skipped_not_registered", started_at, url=url, reason=reason)

    def error(self, nik: str, started_at: str, exc: Exception, url: str = ""):
        row = TransactionRow(
            operator=self.operator or "",
            nik=nik,
            status="error",
            reason=str(exc),
            started_at=started_at or self.run_started_at,
            finished_at=now_iso(),
            url=url,
            error=traceback.format_exc(),
        )
        self.rows.append(row)
        self._append_realtime(row)

    def _add(
        self, nik: str, status: str, started_at: str, url: str = "", reason: str = ""
    ):
        row = TransactionRow(
            operator=self.operator or "",
            nik=nik,
            status=status,
            reason=reason,
            started_at=started_at or self.run_started_at,
            finished_at=now_iso(),
            url=url,
        )
        self.rows.append(row)
        self._append_realtime(row)

    def _init_csv(self):
        need_header = True
        if self.csv_path.exists() and self.csv_path.stat().st_size > 0:
            need_header = False
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._fieldnames)
            if need_header:
                writer.writeheader()
                f.flush()
                os.fsync(f.fileno())

    def _append_realtime(self, row: TransactionRow):
        # Append to CSV
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._fieldnames)
            writer.writerow(asdict(row))
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass  # fsync may not be necessary/available on all systems

        # Append to JSON Lines
        with self.jsonl_path.open("a", encoding="utf-8") as jf:
            jf.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
            jf.flush()
            try:
                os.fsync(jf.fileno())
            except Exception:
                pass

        # Update meta (counts + timestamps) after each row
        self._write_meta()

    def _write_meta(self):
        payload = {
            "operator": self.operator,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": self.summary(),
            "files": {
                "csv": str(self.csv_path),
                "jsonl": str(self.jsonl_path),
                "final_snapshot": str(self.final_json_path),
            },
            "paths": {
                "day_dir": str(self.base_dir),
                "run_dir": str(self.run_dir),
            },
        }
        self.meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def write_files(self, run_name: str | None = None):
        # Final snapshot JSON (full payload) for compatibility
        payload = {
            "operator": self.operator,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": self.summary(),
            "items": [asdict(r) for r in self.rows],
        }
        self.final_json_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False)
        )
        print(
            f"Report written: {self.final_json_path}, {self.csv_path}, {self.jsonl_path}"
        )

    def summary(self) -> dict:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.status] = out.get(r.status, 0) + 1
        out["total"] = len(self.rows)
        return out

    def print_summary(self):
        s = self.summary()
        print("Run summary:")
        for k, v in s.items():
            print(f"- {k}: {v}")
