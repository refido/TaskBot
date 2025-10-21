# src/reporting/reporter.py
import csv
import json
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


class TransactionReporter:
    def __init__(self, out_dir: str = "reports"):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.run_started_at = now_iso()
        self.rows: list[TransactionRow] = []

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
        self.rows.append(
            TransactionRow(
                nik=nik,
                status="error",
                reason=str(exc),
                started_at=started_at or self.run_started_at,
                finished_at=now_iso(),
                url=url,
                error=traceback.format_exc(),
            )
        )

    def _add(
        self, nik: str, status: str, started_at: str, url: str = "", reason: str = ""
    ):
        self.rows.append(
            TransactionRow(
                nik=nik,
                status=status,
                reason=reason,
                started_at=started_at or self.run_started_at,
                finished_at=now_iso(),
                url=url,
            )
        )

    def write_files(self, run_name: str | None = None):
        run_ended_at = now_iso()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"transactions_{run_name or stamp}"
        json_path = self.out_dir / f"{base}.json"
        csv_path = self.out_dir / f"{base}.csv"

        payload = {
            "run_started_at": self.run_started_at,
            "run_ended_at": run_ended_at,
            "counts": self.summary(),
            "items": [asdict(r) for r in self.rows],
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))

        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "nik",
                    "status",
                    "reason",
                    "started_at",
                    "finished_at",
                    "url",
                    "error",
                ],
            )
            writer.writeheader()
            for r in self.rows:
                writer.writerow(asdict(r))

        print(f"Report written: {json_path} and {csv_path}")

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
