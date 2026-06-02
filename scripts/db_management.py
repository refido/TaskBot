from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.database import OperatorDatabaseManager
from src.logging_utils import configure_logging, logger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize TaskBot PostgreSQL tables and sync report rows."
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "init",
        help="Create the configured database if needed, then create OPERATOR_1 and OPERATOR_2.",
    )

    sync_parser = subparsers.add_parser(
        "sync-report",
        help="Sync an items CSV, JSONL, or snapshot JSON report into an operator table.",
    )
    sync_parser.add_argument(
        "report_path", help="Path to items.csv, items.jsonl, or items_snapshot.json."
    )
    sync_parser.add_argument(
        "--table",
        choices=("OPERATOR_1", "OPERATOR_2"),
        help="Force all report rows into a specific table.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "init"
    logging_meta = configure_logging(app_name="db_management")

    logger.bind(
        event="db_management.started",
        command=command,
        report_path=str(getattr(args, "report_path", "")),
        table_name=getattr(args, "table", None),
        run_id=logging_meta["run_id"],
        json_log_path=logging_meta["json_log_path"],
        db_json_log_path=logging_meta["db_json_log_path"],
    ).info("Database management command started")

    try:
        require_targets = command == "sync-report"
        manager = OperatorDatabaseManager.from_env(
            require_operator_targets=require_targets
        )
        manager.ensure_database_and_tables()

        if command == "init":
            logger.bind(
                event="db_management.finished",
                command=command,
            ).info("Database management command finished")
            print("Database and OPERATOR_1/OPERATOR_2 tables are ready.")
            return 0

        if command == "sync-report":
            summary = manager.sync_report_file(args.report_path, table_name=args.table)
            logger.bind(
                event="db_management.finished",
                command=command,
                report_path=summary.source,
                table_name=args.table,
                processed=summary.processed,
                inserted_or_updated=summary.inserted_or_updated,
                skipped=summary.skipped,
            ).info("Database management command finished")
            print(
                "Report sync complete: "
                f"processed={summary.processed}, "
                f"inserted_or_updated={summary.inserted_or_updated}, "
                f"skipped={summary.skipped}, "
                f"source={summary.source}"
            )
            return 0
    except Exception:
        logger.bind(
            event="db_management.failed",
            command=command,
            report_path=str(getattr(args, "report_path", "")),
            table_name=getattr(args, "table", None),
            json_log_path=logging_meta["json_log_path"],
            db_json_log_path=logging_meta["db_json_log_path"],
        ).exception("Database management command failed")
        print(
            "Database management failed. "
            f"See DB log file: {logging_meta['db_json_log_path']}",
            file=sys.stderr,
        )
        return 1

    parser.error(f"Unsupported command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
