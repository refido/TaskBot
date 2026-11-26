"""Inspect and recover quota records without starting a shop session."""

import argparse
import json
from datetime import datetime

from src.infrastructure.database.operator_store import OperatorDatabaseManager
from src.infrastructure.database.report_syncer import DatabaseReportSyncer


def receipt_time(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Provide the receipt time in ISO format with its time zone"
        ) from exc
    if timestamp.utcoffset() is None:
        raise argparse.ArgumentTypeError("The receipt time must include its time zone")
    return timestamp.isoformat()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operator", help="Configured operator ID")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser(
        "list", help="List outstanding events with masked customer numbers"
    )
    commands.add_parser("drain", help="Send known outcomes to the database")
    confirmed = commands.add_parser(
        "confirmed", help="Record a sale verified against the shop receipt"
    )
    confirmed.add_argument("event_id")
    confirmed.add_argument("receipt_time", type=receipt_time)
    no_sale = commands.add_parser(
        "no-sale", help="Clear an open item after verifying there was no sale"
    )
    no_sale.add_argument("event_id")
    args = parser.parse_args(argv)
    syncer = DatabaseReportSyncer()
    try:
        manager = OperatorDatabaseManager.from_env()
        journal = syncer.open_journal(args.operator, manager)
        if args.action == "list":
            labels = ("needs receipt check", "pending delivery", "confirmed")
            for row in journal.entries():
                payload = json.loads(row["payload"])
                nik = str(payload["nik"])
                masked = "****" + (nik[-4:] if len(nik) > 4 else "")
                print(
                    row["id"],
                    labels[row["ready"]],
                    masked,
                    payload.get("finished_at") or payload.get("started_at"),
                )
            return
        if args.action in ("confirmed", "no-sale"):
            journal.reconcile(
                args.event_id, confirmed_at=getattr(args, "receipt_time", None)
            )
        syncer.finish_delivery()
        journal.require_resolved()
        print("Quota recovery complete.")
    finally:
        syncer.close()


if __name__ == "__main__":
    main()
