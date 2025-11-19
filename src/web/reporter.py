import csv
import json
import os
import traceback
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


def now_iso() -> str:
    """Get current timestamp in ISO format"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso(iso_str: str) -> datetime:
    """Parse ISO format timestamp to datetime object"""
    try:
        return datetime.fromisoformat(iso_str)
    except Exception:
        return datetime.now().astimezone()


@dataclass
class TransactionRow:
    """Data model for a single transaction record"""

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
        """Calculate duration between started_at and finished_at"""
        if self.started_at and self.finished_at:
            try:
                start = parse_iso(self.started_at)
                finish = parse_iso(self.finished_at)
                self.duration_seconds = (finish - start).total_seconds()
            except Exception:
                self.duration_seconds = 0.0


class FileWriter:
    """Handles file I/O operations for transaction data"""

    def __init__(self, csv_path: Path, jsonl_path: Path):
        self.csv_path = csv_path
        self.jsonl_path = jsonl_path
        self.fieldnames = [
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

    def init_csv(self) -> None:
        """Initialize CSV file with headers if needed"""
        need_header = not (self.csv_path.exists() and self.csv_path.stat().st_size > 0)

        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            if need_header:
                writer.writeheader()
                self._flush_file(f)

    def append_row(self, row: TransactionRow) -> None:
        """Append a row to both CSV and JSONL files"""
        self._append_to_csv(row)
        self._append_to_jsonl(row)

    def _append_to_csv(self, row: TransactionRow) -> None:
        """Append row to CSV file"""
        with self.csv_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writerow(asdict(row))
            self._flush_file(f)

    def _append_to_jsonl(self, row: TransactionRow) -> None:
        """Append row to JSONL file"""
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
            self._flush_file(f)

    @staticmethod
    def _flush_file(file_handle) -> None:
        """Flush and sync file to disk"""
        file_handle.flush()
        try:
            os.fsync(file_handle.fileno())
        except Exception:
            pass

    def write_json(self, path: Path, data: dict) -> None:
        """Write JSON data to file"""
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


class MetricsCalculator:
    """Calculates analytics and metrics from transaction data"""

    def __init__(self, rows: List[TransactionRow]):
        self.rows = rows

    def get_summary(self) -> Dict[str, int]:
        """Get count summary by status"""
        counts = defaultdict(int)
        for row in self.rows:
            counts[row.status] += 1
        counts["total"] = len(self.rows)
        return dict(counts)

    def get_analytics(self, run_started_at: str) -> Dict:
        """Generate comprehensive analytics"""
        if not self.rows:
            return self._empty_analytics()

        summary = self._calculate_summary()
        performance = self._calculate_performance(run_started_at)
        puzzle_metrics = self._calculate_puzzle_metrics()

        return {
            "summary": summary,
            "performance": performance,
            "puzzle_metrics": puzzle_metrics,
            "breakdown_by_status": self._get_status_breakdown(),
            "skip_reasons": self._get_skip_reasons(),
            "error_analysis": self._get_error_analysis(),
        }

    def _calculate_summary(self) -> Dict:
        """Calculate summary statistics"""
        total = len(self.rows)
        counts = self.get_summary()

        completed = counts.get("completed", 0)
        errors = counts.get("error", 0)
        skipped = sum(counts.get(k, 0) for k in counts if k.startswith("skipped_"))

        return {
            "total_transactions": total,
            "completed": completed,
            "errors": errors,
            "skipped": skipped,
            "success_rate_percent": self._safe_percentage(completed, total),
            "error_rate_percent": self._safe_percentage(errors, total),
            "skip_rate_percent": self._safe_percentage(skipped, total),
        }

    def _calculate_performance(self, run_started_at: str) -> Dict:
        """Calculate performance metrics"""
        durations = [r.duration_seconds for r in self.rows if r.duration_seconds > 0]
        completed_durations = [
            r.duration_seconds
            for r in self.rows
            if r.status == "completed" and r.duration_seconds > 0
        ]

        try:
            run_start = parse_iso(run_started_at)
            run_end = datetime.now().astimezone()
            total_runtime = (run_end - run_start).total_seconds()
            throughput = (
                len(self.rows) / (total_runtime / 60) if total_runtime > 0 else 0.0
            )
        except Exception:
            total_runtime = 0.0
            throughput = 0.0

        return {
            "total_runtime_seconds": round(total_runtime, 2),
            "total_runtime_minutes": round(total_runtime / 60, 2),
            "throughput_per_minute": round(throughput, 2),
            "avg_duration_seconds": self._safe_average(durations),
            "min_duration_seconds": round(min(durations), 3) if durations else 0.0,
            "max_duration_seconds": round(max(durations), 3) if durations else 0.0,
            "avg_completed_duration_seconds": self._safe_average(completed_durations),
        }

    def _calculate_puzzle_metrics(self) -> Dict:
        """Calculate puzzle-specific metrics"""
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

    def _get_status_breakdown(self) -> Dict:
        """Get detailed breakdown by status"""
        breakdown = defaultdict(lambda: {"count": 0, "durations": []})

        for row in self.rows:
            breakdown[row.status]["count"] += 1
            if row.duration_seconds > 0:
                breakdown[row.status]["durations"].append(row.duration_seconds)

        total = len(self.rows)
        result = {}
        for status, data in breakdown.items():
            durations = data["durations"]
            result[status] = {
                "count": data["count"],
                "percentage": self._safe_percentage(data["count"], total),
                "avg_duration_seconds": self._safe_average(durations),
            }

        return result

    def _get_skip_reasons(self) -> Dict[str, int]:
        """Aggregate skip reasons"""
        skip_reasons = defaultdict(int)
        for row in self.rows:
            if row.status.startswith("skipped_") and row.reason:
                skip_reasons[row.reason] += 1
        return dict(skip_reasons)

    def _get_error_analysis(self) -> Dict:
        """Analyze error patterns"""
        error_types = defaultdict(int)
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
        """Calculate percentage safely"""
        return round((value / total * 100), 2) if total > 0 else 0.0

    @staticmethod
    def _safe_average(values: List[float]) -> float:
        """Calculate average safely"""
        return round(sum(values) / len(values), 3) if values else 0.0

    @staticmethod
    def _empty_analytics() -> Dict:
        """Return empty analytics structure"""
        return {
            "summary": {
                "total_transactions": 0,
                "completed": 0,
                "errors": 0,
                "skipped": 0,
                "success_rate_percent": 0.0,
                "error_rate_percent": 0.0,
                "skip_rate_percent": 0.0,
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
    """Main reporter class for managing transaction logging and analytics"""

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

        # Setup directory structure
        self._setup_directories(out_dir, run_name, per_run_subdir)

        # Initialize file writer
        self.file_writer = FileWriter(self.csv_path, self.jsonl_path)
        self.file_writer.init_csv()

        # Initialize JSONL
        if not self.jsonl_path.exists():
            self.jsonl_path.touch()

        self._write_meta()

    def _setup_directories(
        self, out_dir: str, run_name: Optional[str], per_run_subdir: bool
    ) -> None:
        """Setup directory structure for reports"""
        run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        day_stamp = datetime.now().strftime("%Y-%m-%d")

        self.base_dir = Path(out_dir) / day_stamp
        self.run_dir = (
            self.base_dir / (run_name or run_stamp) if per_run_subdir else self.base_dir
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Define file paths
        self.csv_path = self.run_dir / "items.csv"
        self.jsonl_path = self.run_dir / "items.jsonl"
        self.meta_path = self.run_dir / "run_meta.json"
        self.final_json_path = self.run_dir / "items_snapshot.json"
        self.analytics_path = self.run_dir / "analytics.json"

    def start_item(self, nik: str) -> str:
        """Start timing for a new item"""
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
        """Record a completed transaction"""
        self._add_row(
            "completed", nik, started_at, url, puzzle_solved, puzzle_attempts, reason
        )

    def skip(
        self, nik: str, started_at: str, skip_type: str, url: str = "", reason: str = ""
    ) -> None:
        """Record a skipped transaction with specific type"""
        status = f"skipped_{skip_type}"
        self._add_row(status, nik, started_at, url, reason=reason)

    def skip_max_kuota(
        self, nik: str, started_at: str, url: str = "", reason: str = "Max kuota alert"
    ) -> None:
        """Record max kuota skip"""
        self.skip(nik, started_at, "max_kuota", url, reason)

    def skip_needs_update(
        self,
        nik: str,
        started_at: str,
        url: str = "",
        reason: str = "Needs data update",
    ) -> None:
        """Record needs update skip"""
        self.skip(nik, started_at, "needs_update", url, reason)

    def skip_not_registered(
        self, nik: str, started_at: str, url: str = "", reason: str = "Not registered"
    ) -> None:
        """Record not registered skip"""
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
        """Record an error"""
        row = self._create_row(
            "error",
            nik,
            started_at,
            url,
            puzzle_solved,
            puzzle_attempts,
            str(exc),
            traceback.format_exc(),
        )
        self._record_row(row)

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
        """Add a new row to records"""
        row = self._create_row(
            status, nik, started_at, url, puzzle_solved, puzzle_attempts, reason, error
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
        """Create a TransactionRow instance"""
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
        """Record a row and append to files"""
        self.rows.append(row)
        self.file_writer.append_row(row)
        self._write_meta()

    def _write_meta(self) -> None:
        """Write metadata file"""
        calculator = MetricsCalculator(self.rows)
        payload = {
            "operator": self.operator,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": calculator.get_summary(),
            "analytics": calculator.get_analytics(self.run_started_at),
            "files": {
                "csv": str(self.csv_path),
                "jsonl": str(self.jsonl_path),
                "final_snapshot": str(self.final_json_path),
                "analytics": str(self.analytics_path),
            },
            "paths": {"day_dir": str(self.base_dir), "run_dir": str(self.run_dir)},
        }
        self.file_writer.write_json(self.meta_path, payload)

    def write_files(self, run_name: Optional[str] = None) -> None:
        """Write final snapshot files"""
        calculator = MetricsCalculator(self.rows)
        payload = {
            "operator": self.operator,
            "run_started_at": self.run_started_at,
            "run_ended_at": now_iso(),
            "counts": calculator.get_summary(),
            "analytics": calculator.get_analytics(self.run_started_at),
            "items": [asdict(r) for r in self.rows],
        }

        self.file_writer.write_json(self.final_json_path, payload)
        self.file_writer.write_json(
            self.analytics_path, calculator.get_analytics(self.run_started_at)
        )

        print(
            f"Report written: {self.final_json_path}, {self.csv_path}, {self.jsonl_path}, {self.analytics_path}"
        )

    def summary(self) -> Dict[str, int]:
        """Get summary counts"""
        return MetricsCalculator(self.rows).get_summary()

    def get_analytics(self) -> Dict:
        """Get comprehensive analytics"""
        return MetricsCalculator(self.rows).get_analytics(self.run_started_at)

    def get_rows_by_status(self, status: str) -> List[TransactionRow]:
        """Filter rows by status"""
        return [r for r in self.rows if r.status == status]

    def get_failed_niks(self) -> List[str]:
        """Get list of failed NIKs"""
        return [
            r.nik
            for r in self.rows
            if r.status == "error" or r.status.startswith("skipped_")
        ]

    def get_successful_niks(self) -> List[str]:
        """Get list of successful NIKs"""
        return [r.nik for r in self.rows if r.status == "completed"]

    def get_puzzle_failed_niks(self) -> List[str]:
        """Get NIKs where puzzle solving failed"""
        return [r.nik for r in self.rows if r.puzzle_solved is False]

    def get_puzzle_stats_by_nik(self) -> Dict[str, Dict]:
        """Get puzzle statistics grouped by NIK"""
        nik_stats = defaultdict(lambda: {"attempts": 0, "solved": False})
        for row in self.rows:
            if row.puzzle_solved is not None:
                nik_stats[row.nik]["attempts"] = row.puzzle_attempts
                nik_stats[row.nik]["solved"] = row.puzzle_solved
        return dict(nik_stats)

    def print_summary(self) -> None:
        """Print comprehensive summary"""
        analytics = self.get_analytics()

        print("\n" + "=" * 60)
        print("RUN SUMMARY")
        print("=" * 60)

        self._print_section("Transaction Counts", analytics["summary"], ["_percent"])
        self._print_section(
            "Success Rates",
            analytics["summary"],
            ["success", "error", "skip"],
            suffix="_percent",
        )
        self._print_performance(analytics["performance"])
        self._print_puzzle_metrics(analytics["puzzle_metrics"])
        self._print_status_breakdown(analytics["breakdown_by_status"])
        self._print_skip_reasons(analytics["skip_reasons"])
        self._print_error_analysis(analytics["error_analysis"])

        print("\n" + "=" * 60)
        print(f"Analytics saved to: {self.analytics_path}")
        print("=" * 60 + "\n")

    def _print_section(
        self, title: str, data: Dict, filters: List[str] = None, suffix: str = ""
    ) -> None:
        """Print a section of analytics"""
        print(f"\n{title}:")
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
                print(f"  {label}: {value:.2f}{'%' if '_percent' in key else ''}")
            else:
                print(f"  {label}: {value}")

    def _print_performance(self, perf: Dict) -> None:
        """Print performance metrics"""
        print("\nPerformance Metrics:")
        print(f"  Total Runtime: {perf['total_runtime_minutes']:.2f} minutes")
        print(f"  Throughput: {perf['throughput_per_minute']:.2f} items/minute")
        print(f"  Avg Duration: {perf['avg_duration_seconds']:.3f} seconds")
        if perf["avg_completed_duration_seconds"] > 0:
            print(
                f"  Avg Completed Duration: {perf['avg_completed_duration_seconds']:.3f} seconds"
            )

    def _print_puzzle_metrics(self, puzzle: Dict) -> None:
        """Print puzzle metrics"""
        if puzzle.get("total_puzzles", 0) > 0:
            print("\nPuzzle Solving Metrics:")
            print(f"  Total Puzzles: {puzzle['total_puzzles']}")
            print(
                f"  Solved: {puzzle['puzzles_solved']} ({puzzle['puzzle_success_rate_percent']}%)"
            )
            print(
                f"  Failed: {puzzle['puzzles_failed']} ({puzzle['puzzle_failure_rate_percent']}%)"
            )
            print(f"  Avg Attempts: {puzzle['avg_attempts']:.2f}")
            if puzzle["avg_solved_duration_seconds"] > 0:
                print(f"  Avg Solve Time: {puzzle['avg_solved_duration_seconds']:.3f}s")
            if puzzle["avg_failed_duration_seconds"] > 0:
                print(
                    f"  Avg Failed Time: {puzzle['avg_failed_duration_seconds']:.3f}s"
                )

    def _print_status_breakdown(self, breakdown: Dict) -> None:
        """Print status breakdown"""
        print("\nStatus Breakdown:")
        for status, data in breakdown.items():
            print(
                f"  {status}: {data['count']} ({data['percentage']}%) - avg {data['avg_duration_seconds']:.3f}s"
            )

    def _print_skip_reasons(self, reasons: Dict) -> None:
        """Print skip reasons"""
        if reasons:
            print("\nTop Skip Reasons:")
            for reason, count in list(reasons.items())[:5]:
                print(f"  {reason}: {count}")

    def _print_error_analysis(self, analysis: Dict) -> None:
        """Print error analysis"""
        if analysis["total_errors"] > 0:
            print("\nError Analysis:")
            print(f"  Total Errors: {analysis['total_errors']}")
            print(f"  Unique Error Types: {analysis['unique_error_types']}")
            if analysis["error_frequency"]:
                print("  Top Errors:")
                for error, count in list(analysis["error_frequency"].items())[:3]:
                    print(f"    {error[:80]}...: {count}")
