from __future__ import annotations

import csv
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

from src.logging_utils import logger
from src.privacy import register_private_values

OPERATOR_TABLE_NAMES = ("OPERATOR_1", "OPERATOR_2")
TIMESTAMP_FORMAT = "%Y%m%d %H%M%S"

_OPERATOR_TABLE_PATTERN = re.compile(r"^OPERATOR_\d+$")
_NUMBERED_TARGET_KEY_PATTERN = re.compile(
    r"^(?:NAME_OPERATORS|EMAIL|PIN|NIK)_(\d+)$|^OPERATOR_(\d+)_ID$"
)
_NUMBERED_ACCOUNT_KEY_PATTERN = re.compile(r"^(?:EMAIL|PIN|NIK)_(\d+)$")

_COLUMN_NAMES = (
    "OPERATOR",
    "NIK",
    "NAMA_KONSUMER",
    "KUOTA",
    "MAX_KUOTA",
    "CONFLICT",
    "STATUS_CODE",
    "STATUS_CODE_DESCRIPTION",
    "PROBLEM",
    "LAST_TRANSACTION_TIME",
    "PREVIOUS_TRANSACTION_TIME",
    "UPDATED_TIME",
    "CREATED_TIME",
)
_NAME_FIELDS = ("nama", "NAMA", "name", "NAME", "customer_name", "customerName")
_SUCCESS_STATUSES = {"completed", "success", "successful"}
_DEFAULT_STATUS = "unknown"


@dataclass(frozen=True, slots=True)
class ReportStatusMapping:
    status_code: int
    description: str


_STATUS_MAPPINGS = {
    "completed": ReportStatusMapping(200, "Transaction successful"),
    "success": ReportStatusMapping(200, "Transaction successful"),
    "successful": ReportStatusMapping(200, "Transaction successful"),
    "skipped_max_kuota": ReportStatusMapping(409, "Max kuota reached"),
    "skipped_out_of_stock": ReportStatusMapping(409, "Sellable stock unavailable"),
    "skipped_not_registered": ReportStatusMapping(404, "Consumer not registered"),
    "skipped_registration_request_limited": ReportStatusMapping(
        429, "Consumer registration request limit reached"
    ),
    "failed_puzzle_solve": ReportStatusMapping(422, "Puzzle solving failed"),
    "skipped_need updated customer data": ReportStatusMapping(
        422, "Consumer data needs update"
    ),
    "skipped_nik is not yet 17 years old": ReportStatusMapping(
        422, "Consumer is under 17"
    ),
    "skipped_the registered customer's nik is invalid": ReportStatusMapping(
        422, "Registered consumer NIK is invalid"
    ),
    "skipped_customers cannot transact at this base": ReportStatusMapping(
        409, "Consumer cannot transact at this base"
    ),
    "skipped_the customer's nik indicates an unusual transaction at another base with an unusual distance and close time.": ReportStatusMapping(
        409, "Unusual transaction at another base"
    ),
    "error": ReportStatusMapping(500, "Transaction error"),
}
_DEFAULT_SKIPPED_MAPPING = ReportStatusMapping(400, "Transaction skipped")
_DEFAULT_ERROR_MAPPING = ReportStatusMapping(500, "Transaction error")
_DEFAULT_UNKNOWN_MAPPING = ReportStatusMapping(520, "Unknown transaction status")


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    host: str
    port: int
    name: str
    user: str
    password: str
    maintenance_name: str = "postgres"

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> DatabaseConfig:
        if load_env_file:
            load_dotenv()

        source = os.environ if environ is None else environ
        missing = [
            key
            for key in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
            if not source.get(key, "").strip()
        ]
        if missing:
            raise ValueError(
                f"Missing database environment variables: {', '.join(missing)}"
            )

        try:
            port = int(source["DB_PORT"])
        except ValueError as exc:
            raise ValueError("DB_PORT must be a number.") from exc

        password = source["DB_PASSWORD"]
        register_private_values(password)
        return cls(
            host=source["DB_HOST"].strip(),
            port=port,
            name=source["DB_NAME"].strip(),
            user=source["DB_USER"].strip(),
            password=password,
            maintenance_name=source.get("DB_MAINTENANCE_NAME", "postgres").strip()
            or "postgres",
        )


@dataclass(frozen=True, slots=True)
class OperatorTarget:
    table_name: str
    operator_name: str
    aliases: tuple[str, ...] = ()
    operator_id: str = ""

    def matches(self, operator: str) -> bool:
        normalized = _normalize_key(operator)
        return any(
            _normalize_key(alias) == normalized
            for alias in (*self.aliases, self.operator_id)
            if alias
        )


@dataclass(frozen=True, slots=True)
class OperatorTargets:
    targets: tuple[OperatorTarget, ...]

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> OperatorTargets:
        if load_env_file:
            load_dotenv()

        source = os.environ if environ is None else environ
        targets: list[OperatorTarget] = []
        configured_operator_ids: dict[str, str] = {}
        numbered_account_configured = any(
            _NUMBERED_ACCOUNT_KEY_PATTERN.fullmatch(key)
            and str(value).strip()
            for key, value in source.items()
        )
        use_legacy_account = not numbered_account_configured and any(
            source.get(key, "").strip() for key in ("EMAIL", "PIN", "NIK")
        )
        suffixes = _collect_operator_suffixes(source)
        if use_legacy_account:
            suffixes.add("1")

        for suffix in sorted(suffixes, key=lambda value: (int(value), value)):
            table_name = f"OPERATOR_{suffix}"
            legacy_target = use_legacy_account and int(suffix) == 1
            email_key = "EMAIL" if legacy_target else f"EMAIL_{suffix}"
            pin_key = "PIN" if legacy_target else f"PIN_{suffix}"
            nik_key = "NIK" if legacy_target else f"NIK_{suffix}"
            operator_id_key = (
                "OPERATOR_ID" if legacy_target else f"OPERATOR_{suffix}_ID"
            )
            target_keys = (
                f"NAME_OPERATORS_{suffix}",
                email_key,
                pin_key,
                nik_key,
                operator_id_key,
            )
            if not any(source.get(key, "").strip() for key in target_keys):
                continue

            operator_name = source.get(f"NAME_OPERATORS_{suffix}", "").strip()
            if not operator_name:
                raise ValueError(f"Missing NAME_OPERATORS_{suffix}.")

            operator_id = (
                source.get(operator_id_key, "").strip()
                or f"operator_{int(suffix):02d}"
            )
            normalized_operator_id = _normalize_key(operator_id)
            existing_table = configured_operator_ids.get(normalized_operator_id)
            if existing_table is not None:
                raise ValueError(
                    "Operator IDs must be unique; "
                    f"{existing_table} and {table_name} use the same ID."
                )
            configured_operator_ids[normalized_operator_id] = table_name

            aliases = _dedupe_nonempty(
                (
                    operator_id,
                    operator_name,
                    source.get(email_key, ""),
                    table_name,
                )
            )
            targets.append(
                OperatorTarget(
                    table_name=table_name,
                    operator_name=operator_name,
                    aliases=aliases,
                    operator_id=operator_id,
                )
            )

        if not targets:
            raise ValueError(
                "No operator targets configured. Define NAME_OPERATORS_<n> for "
                "at least one configured account."
            )

        return cls(tuple(targets))

    def resolve(
        self, operator: str, *, table_name: str | None = None
    ) -> OperatorTarget:
        if table_name:
            normalized_table = _normalize_table_name(table_name)
            for target in self.targets:
                if target.table_name == normalized_table:
                    return target
            raise ValueError(f"Unsupported operator table: {table_name}")

        for target in self.targets:
            if target.matches(operator):
                return target

        configured = ", ".join(
            f"{target.table_name}={target.operator_id}" for target in self.targets
        )
        raise ValueError(
            f"Report operator {operator!r} does not match configured operators: {configured}"
        )


@dataclass(frozen=True, slots=True)
class OperatorDbRecord:
    operator: str
    nik: int
    nama_konsumer: str
    kuota_delta: int
    status_code: int
    status_code_description: str
    problem: str
    conflict: bool
    event_time: datetime

    @classmethod
    def from_report_payload(
        cls,
        payload: Mapping[str, Any],
        target: OperatorTarget,
    ) -> OperatorDbRecord:
        status = _normalize_status(payload.get("status"))
        is_successful = status in _SUCCESS_STATUSES
        status_mapping = _map_report_status(status)
        problem = "" if is_successful else _build_problem(payload)
        event_time = _parse_report_datetime(
            payload.get("finished_at")
            or payload.get("updated_time")
            or payload.get("UPDATED_TIME")
            or payload.get("created_time")
            or payload.get("CREATED_TIME")
        )

        return cls(
            operator=target.operator_name,
            nik=_parse_nik(payload.get("nik") or payload.get("NIK")),
            nama_konsumer=_extract_name(payload),
            kuota_delta=1 if is_successful else 0,
            status_code=status_mapping.status_code,
            status_code_description=status_mapping.description,
            problem=problem,
            conflict=bool(problem),
            event_time=event_time,
        )


@dataclass(frozen=True, slots=True)
class PreviousTransactionReport:
    table_name: str
    operator: str
    nik: int
    previous_transaction_time: datetime
    current_transaction_time: datetime
    kuota_before: int


@dataclass(frozen=True, slots=True)
class SyncSummary:
    source: str
    processed: int = 0
    inserted_or_updated: int = 0
    skipped: int = 0
    previous_transactions: tuple[PreviousTransactionReport, ...] = ()


class OperatorDatabaseManager:
    def __init__(self, config: DatabaseConfig, targets: OperatorTargets | None = None):
        self.config = config
        self.targets = targets

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
        require_operator_targets: bool = True,
    ) -> OperatorDatabaseManager:
        config = DatabaseConfig.from_env(environ, load_env_file=load_env_file)
        targets = (
            OperatorTargets.from_env(environ, load_env_file=False)
            if require_operator_targets
            else None
        )
        return cls(config=config, targets=targets)

    def ensure_database_and_tables(self) -> None:
        table_names = self._operator_table_names()
        logger.bind(
            event="database.ensure.started",
            **self._log_context(),
        ).info("Database setup started")
        try:
            self.ensure_database_exists()
            self.ensure_tables_exist()
            self.reset_monthly_quotas()
        except Exception:
            logger.bind(
                event="database.ensure.failed",
                **self._log_context(),
            ).exception("Database setup failed")
            raise
        logger.bind(
            event="database.ensure.finished",
            tables=list(table_names),
            **self._log_context(),
        ).info("Database setup finished")

    def ensure_database_exists(self) -> None:
        log_context = self._log_context(
            connection_database=self.config.maintenance_name
        )
        logger.bind(
            event="database.database_check.started",
            **log_context,
        ).info("Checking PostgreSQL database")
        connection = self._connect(self.config.maintenance_name)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s",
                    (self.config.name,),
                )
                if cursor.fetchone():
                    logger.bind(
                        event="database.database_check.exists",
                        **log_context,
                    ).info("PostgreSQL database already exists")
                    return

                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(self.config.name)
                    )
                )
                logger.bind(
                    event="database.database_created",
                    **log_context,
                ).info("PostgreSQL database created")
        finally:
            connection.close()

    def ensure_tables_exist(self) -> None:
        table_names = self._operator_table_names()
        logger.bind(
            event="database.tables.ensure.started",
            tables=list(table_names),
            **self._log_context(connection_database=self.config.name),
        ).info("Ensuring PostgreSQL operator tables")
        with (
            self._connect(self.config.name) as connection,
            connection.cursor() as cursor,
        ):
            for table_name in table_names:
                operator_id = self._operator_id_for_table(table_name)
                logger.bind(
                    event="database.table.ensure.started",
                    table_name=table_name,
                    **self._log_context(
                        connection_database=self.config.name,
                        operator_id=operator_id,
                    ),
                ).info("Ensuring PostgreSQL operator table")
                cursor.execute(self._create_table_sql(table_name))
                self._migrate_table_schema(cursor, table_name)
                logger.bind(
                    event="database.table.ensure.finished",
                    table_name=table_name,
                    **self._log_context(
                        connection_database=self.config.name,
                        operator_id=operator_id,
                    ),
                ).info("PostgreSQL operator table is ready")
        logger.bind(
            event="database.tables.ensure.finished",
            tables=list(table_names),
            **self._log_context(connection_database=self.config.name),
        ).info("PostgreSQL operator tables are ready")

    def reset_monthly_quotas(self, reference_time: datetime | None = None) -> None:
        table_names = self._operator_table_names()
        normalized_time = _normalize_datetime(
            reference_time or datetime.now().astimezone()
        )
        row_counts: dict[str, int | None] = {}
        logger.bind(
            event="database.monthly_quota_reset.started",
            reference_time=format_db_datetime(normalized_time),
            tables=list(table_names),
            **self._log_context(connection_database=self.config.name),
        ).info("Monthly quota reset started")
        with (
            self._connect(self.config.name) as connection,
            connection.cursor() as cursor,
        ):
            for table_name in table_names:
                cursor.execute(
                    sql.SQL(
                        """
                        UPDATE {table}
                        SET {kuota} = 0
                        WHERE date_trunc('month', {updated_time})
                              < date_trunc('month', %s::timestamp)
                          AND {kuota} <> 0
                        """
                    ).format(
                        table=sql.Identifier(table_name),
                        kuota=sql.Identifier("KUOTA"),
                        updated_time=sql.Identifier("UPDATED_TIME"),
                    ),
                    (normalized_time,),
                )
                row_counts[table_name] = getattr(cursor, "rowcount", None)
                logger.bind(
                    event="database.monthly_quota_reset.table_finished",
                    table_name=table_name,
                    rows_updated=row_counts[table_name],
                    **self._log_context(
                        connection_database=self.config.name,
                        operator_id=self._operator_id_for_table(table_name),
                    ),
                ).info("Monthly quota reset table finished")
        logger.bind(
            event="database.monthly_quota_reset.finished",
            row_counts=row_counts,
            reference_time=format_db_datetime(normalized_time),
            **self._log_context(connection_database=self.config.name),
        ).info("Monthly quota reset finished")

    def sync_report_file(
        self,
        report_path: str | Path,
        *,
        table_name: str | None = None,
        connection: Any | None = None,
    ) -> SyncSummary:
        path = Path(report_path)

        return self.sync_report_payloads(
            read_report_payloads(path),
            source=str(path),
            table_name=table_name,
            connection=connection,
        )

    def sync_report_payloads(
        self,
        payloads: Iterable[Mapping[str, Any]],
        *,
        source: str,
        table_name: str | None = None,
        connection: Any | None = None,
    ) -> SyncSummary:
        """
        Synchronize one ordered batch of report payloads.

        When a connection is supplied, the caller owns the connection lifecycle.
        Each call still uses its own transaction, allowing one persistent
        PostgreSQL connection to be reused across multiple report rows.
        """
        processed = 0
        changed = 0
        skipped = 0
        previous_transactions: list[PreviousTransactionReport] = []
        sync_operator_id = self._operator_id_for_table(table_name)

        logger.bind(
            event="database.report_sync.started",
            report_path=source,
            table_name=table_name,
            **self._log_context(
                connection_database=self.config.name,
                operator_id=sync_operator_id,
            ),
        ).info("Report database sync started")

        owns_connection = connection is None
        db_connection = (
            self._connect(self.config.name) if owns_connection else connection
        )

        try:
            # psycopg2 connection context creates a transaction boundary.
            #
            # On successful exit:
            #     COMMIT
            #
            # On exception:
            #     ROLLBACK
            #
            # It does NOT close a caller-owned persistent connection.
            with db_connection, db_connection.cursor() as cursor:
                for payload in payloads:
                    processed += 1

                    try:
                        previous_transaction = self.upsert_report_payload(
                            payload,
                            cursor=cursor,
                            table_name=table_name,
                        )

                    except ValueError as exc:
                        skipped += 1

                        logger.bind(
                            event="database.report_sync.row_skipped",
                            report_path=source,
                            row_number=processed,
                            reason=str(exc),
                            **self._log_context(
                                connection_database=self.config.name,
                                operator_id=self._operator_id_for_payload(
                                    payload,
                                    table_name=table_name,
                                ),
                            ),
                        ).warning("Report row skipped during database sync")

                        continue

                    if previous_transaction is not None:
                        previous_transactions.append(previous_transaction)

                    changed += 1

        except Exception:
            logger.bind(
                event="database.report_sync.failed",
                report_path=source,
                table_name=table_name,
                processed=processed,
                inserted_or_updated=changed,
                skipped=skipped,
                **self._log_context(
                    connection_database=self.config.name,
                    operator_id=sync_operator_id,
                ),
            ).exception("Report database sync failed")

            raise

        finally:
            if owns_connection:
                close_connection = getattr(db_connection, "close", None)
                if callable(close_connection):
                    close_connection()

        summary = SyncSummary(
            source=source,
            processed=processed,
            inserted_or_updated=changed,
            skipped=skipped,
            previous_transactions=tuple(previous_transactions),
        )

        logger.bind(
            event="database.report_sync.finished",
            report_path=summary.source,
            table_name=table_name,
            processed=summary.processed,
            inserted_or_updated=summary.inserted_or_updated,
            skipped=summary.skipped,
            previous_transaction_count=len(summary.previous_transactions),
            **self._log_context(
                connection_database=self.config.name,
                operator_id=sync_operator_id,
            ),
        ).info("Report database sync finished")

        return summary

    def upsert_report_payload(
        self,
        payload: Mapping[str, Any],
        *,
        cursor,
        table_name: str | None = None,
    ) -> PreviousTransactionReport | None:
        if self.targets is None:
            raise ValueError("Operator targets are required to sync report payloads.")

        target = self._resolve_payload_target(payload, table_name=table_name)
        record = OperatorDbRecord.from_report_payload(payload, target)
        return self.upsert_record(
            target.table_name,
            record,
            cursor=cursor,
            operator_id=target.operator_id,
        )

    def _resolve_payload_target(
        self,
        payload: Mapping[str, Any],
        *,
        table_name: str | None = None,
    ) -> OperatorTarget:
        if self.targets is None:
            raise ValueError("Operator targets are required to sync report payloads.")

        if table_name is not None:
            return self.targets.resolve("", table_name=table_name)

        identifiers = _dedupe_nonempty(
            (
                str(payload.get("operator_id", "")),
                str(payload.get("operator", "")),
            )
        )
        for identifier in identifiers:
            for target in self.targets.targets:
                if target.matches(identifier):
                    return target

        unresolved_identifier = identifiers[0] if identifiers else ""
        return self.targets.resolve(unresolved_identifier)

    def _operator_id_for_payload(
        self,
        payload: Mapping[str, Any],
        *,
        table_name: str | None = None,
    ) -> str | None:
        try:
            return self._resolve_payload_target(
                payload,
                table_name=table_name,
            ).operator_id
        except ValueError:
            return self._operator_id_for_table(table_name)

    def _operator_id_for_table(self, table_name: str | None) -> str | None:
        if self.targets is None:
            return None
        if table_name is None:
            if len(self.targets.targets) == 1:
                return self.targets.targets[0].operator_id
            return None
        try:
            return self.targets.resolve("", table_name=table_name).operator_id
        except ValueError:
            return None

    def upsert_record(
        self,
        table_name: str,
        record: OperatorDbRecord,
        *,
        cursor,
        operator_id: str | None = None,
    ) -> PreviousTransactionReport | None:
        normalized_table = _normalize_table_name(table_name)
        event_time = _normalize_datetime(record.event_time)
        previous_transaction = self._find_previous_transaction(
            normalized_table,
            record,
            event_time=event_time,
            cursor=cursor,
        )
        last_transaction_time = event_time if record.kuota_delta > 0 else None
        previous_transaction_time = (
            previous_transaction.previous_transaction_time
            if previous_transaction is not None
            else None
        )
        cursor.execute(
            self._upsert_sql(normalized_table),
            (
                record.operator,
                record.nik,
                record.nama_konsumer,
                record.kuota_delta,
                record.kuota_delta,
                record.conflict,
                record.status_code,
                record.status_code_description,
                record.problem,
                last_transaction_time,
                previous_transaction_time,
                event_time,
                event_time,
            ),
        )
        logger.bind(
            event="database.report_sync.row_upserted",
            table_name=normalized_table,
            operator=record.operator,
            nik=record.nik,
            status_code=record.status_code,
            conflict=record.conflict,
            event_time=format_db_datetime(event_time),
            **self._log_context(
                connection_database=self.config.name,
                operator_id=operator_id,
            ),
        ).debug("Report row upserted into database")
        if previous_transaction is not None:
            logger.bind(
                event="database.report_sync.previous_transaction_detected",
                table_name=normalized_table,
                operator=record.operator,
                nik=record.nik,
                previous_transaction_time=format_db_datetime(
                    previous_transaction.previous_transaction_time
                ),
                current_transaction_time=format_db_datetime(event_time),
                kuota_before=previous_transaction.kuota_before,
                **self._log_context(
                    connection_database=self.config.name,
                    operator_id=operator_id,
                ),
            ).info("Previous successful transaction found for report NIK")
        return previous_transaction

    @staticmethod
    def _find_previous_transaction(
        table_name: str,
        record: OperatorDbRecord,
        *,
        event_time: datetime,
        cursor,
    ) -> PreviousTransactionReport | None:
        if record.kuota_delta <= 0:
            return None

        normalized_table = _normalize_table_name(table_name)
        last_transaction_time = sql.Identifier("LAST_TRANSACTION_TIME")
        updated_time = sql.Identifier("UPDATED_TIME")
        kuota = sql.Identifier("KUOTA")
        nik = sql.Identifier("NIK")
        cursor.execute(
            sql.SQL(
                """
                SELECT {last_transaction_time}, {updated_time}, {kuota}
                FROM {table}
                WHERE {nik} = %s
                """
            ).format(
                table=sql.Identifier(normalized_table),
                last_transaction_time=last_transaction_time,
                updated_time=updated_time,
                kuota=kuota,
                nik=nik,
            ),
            (record.nik,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        stored_last_transaction_time, stored_updated_time, stored_kuota = row
        current_stored_time = _coerce_db_datetime(stored_updated_time)
        if current_stored_time is not None and event_time <= current_stored_time:
            return None

        kuota_before = int(stored_kuota or 0)
        previous_transaction_time = _coerce_db_datetime(stored_last_transaction_time)
        if previous_transaction_time is None and kuota_before > 0:
            previous_transaction_time = current_stored_time

        if previous_transaction_time is None:
            return None

        return PreviousTransactionReport(
            table_name=normalized_table,
            operator=record.operator,
            nik=record.nik,
            previous_transaction_time=previous_transaction_time,
            current_transaction_time=event_time,
            kuota_before=kuota_before,
        )

    def _connect(self, database_name: str):
        logger.bind(
            event="database.connection.opening",
            **self._log_context(connection_database=database_name),
        ).debug("Opening PostgreSQL connection")
        return psycopg2.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=database_name,
            user=self.config.user,
            password=self.config.password,
        )

    def open_connection(self):
        """Open a connection to the configured application database."""
        return self._connect(self.config.name)

    def _operator_table_names(self) -> tuple[str, ...]:
        if self.targets is None:
            return OPERATOR_TABLE_NAMES
        return tuple(
            dict.fromkeys(
                _normalize_table_name(target.table_name)
                for target in self.targets.targets
            )
        )

    def _log_context(
        self,
        *,
        connection_database: str | None = None,
        operator_id: str | None = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "db_host": self.config.host,
            "db_port": self.config.port,
            "db_name": self.config.name,
        }
        if connection_database is not None:
            context["connection_database"] = connection_database

        configured_operator_ids = (
            [
                target.operator_id
                for target in self.targets.targets
                if target.operator_id
            ]
            if self.targets is not None
            else []
        )
        if configured_operator_ids:
            context["operator_ids"] = configured_operator_ids

        resolved_operator_id = operator_id
        if resolved_operator_id is None and len(configured_operator_ids) == 1:
            resolved_operator_id = configured_operator_ids[0]
        if resolved_operator_id:
            context["operator_id"] = resolved_operator_id

        return context

    @staticmethod
    def _create_table_sql(table_name: str):
        identifiers = {
            column_name.lower(): sql.Identifier(column_name)
            for column_name in _COLUMN_NAMES
        }
        return sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {table} (
                {operator} TEXT NOT NULL DEFAULT '',
                {nik} BIGINT PRIMARY KEY,
                {nama_konsumer} TEXT NOT NULL DEFAULT '',
                {kuota} INTEGER NOT NULL DEFAULT 0,
                {max_kuota} INTEGER NOT NULL DEFAULT 0,
                {conflict} BOOLEAN NOT NULL DEFAULT FALSE,
                {status_code} INTEGER NOT NULL DEFAULT 0,
                {status_code_description} TEXT NOT NULL DEFAULT '',
                {problem} TEXT NOT NULL DEFAULT '',
                {last_transaction_time} TIMESTAMP WITHOUT TIME ZONE,
                {previous_transaction_time} TIMESTAMP WITHOUT TIME ZONE,
                {updated_time} TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                {created_time} TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ).format(
            table=sql.Identifier(_normalize_table_name(table_name)),
            operator=identifiers["operator"],
            nik=identifiers["nik"],
            nama_konsumer=identifiers["nama_konsumer"],
            kuota=identifiers["kuota"],
            max_kuota=identifiers["max_kuota"],
            conflict=identifiers["conflict"],
            status_code=identifiers["status_code"],
            status_code_description=identifiers["status_code_description"],
            problem=identifiers["problem"],
            last_transaction_time=identifiers["last_transaction_time"],
            previous_transaction_time=identifiers["previous_transaction_time"],
            updated_time=identifiers["updated_time"],
            created_time=identifiers["created_time"],
        )

    @staticmethod
    def _migrate_table_schema(cursor, table_name: str) -> None:
        normalized_table = _normalize_table_name(table_name)
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %s
            """,
            (normalized_table,),
        )
        existing_columns = {str(row[0]).upper() for row in cursor.fetchall()}
        should_backfill_last_transaction_time = (
            "LAST_TRANSACTION_TIME" not in existing_columns
        )

        if "NAMA" in existing_columns and "OPERATOR" not in existing_columns:
            cursor.execute(
                sql.SQL("ALTER TABLE {table} RENAME COLUMN {old} TO {new}").format(
                    table=sql.Identifier(normalized_table),
                    old=sql.Identifier("NAMA"),
                    new=sql.Identifier("OPERATOR"),
                )
            )
            existing_columns.discard("NAMA")
            existing_columns.add("OPERATOR")

        add_columns = (
            ("OPERATOR", sql.SQL("TEXT NOT NULL DEFAULT ''")),
            ("NAMA_KONSUMER", sql.SQL("TEXT NOT NULL DEFAULT ''")),
            ("KUOTA", sql.SQL("INTEGER NOT NULL DEFAULT 0")),
            ("MAX_KUOTA", sql.SQL("INTEGER NOT NULL DEFAULT 0")),
            ("CONFLICT", sql.SQL("BOOLEAN NOT NULL DEFAULT FALSE")),
            ("STATUS_CODE", sql.SQL("INTEGER NOT NULL DEFAULT 0")),
            ("STATUS_CODE_DESCRIPTION", sql.SQL("TEXT NOT NULL DEFAULT ''")),
            ("PROBLEM", sql.SQL("TEXT NOT NULL DEFAULT ''")),
            (
                "LAST_TRANSACTION_TIME",
                sql.SQL("TIMESTAMP WITHOUT TIME ZONE"),
            ),
            (
                "PREVIOUS_TRANSACTION_TIME",
                sql.SQL("TIMESTAMP WITHOUT TIME ZONE"),
            ),
            (
                "UPDATED_TIME",
                sql.SQL(
                    "TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ),
            ),
            (
                "CREATED_TIME",
                sql.SQL(
                    "TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ),
            ),
        )
        for column_name, column_type in add_columns:
            if column_name in existing_columns:
                continue
            cursor.execute(
                sql.SQL("ALTER TABLE {table} ADD COLUMN {column} {column_type}").format(
                    table=sql.Identifier(normalized_table),
                    column=sql.Identifier(column_name),
                    column_type=column_type,
                )
            )
            existing_columns.add(column_name)

        if should_backfill_last_transaction_time:
            cursor.execute(
                sql.SQL(
                    """
                    UPDATE {table}
                    SET {last_transaction_time} = {updated_time}
                    WHERE {kuota} > 0
                      AND {last_transaction_time} IS NULL
                    """
                ).format(
                    table=sql.Identifier(normalized_table),
                    last_transaction_time=sql.Identifier("LAST_TRANSACTION_TIME"),
                    updated_time=sql.Identifier("UPDATED_TIME"),
                    kuota=sql.Identifier("KUOTA"),
                )
            )

    @staticmethod
    def _upsert_sql(table_name: str):
        table = sql.Identifier(_normalize_table_name(table_name))
        operator = sql.Identifier("OPERATOR")
        nik = sql.Identifier("NIK")
        nama_konsumer = sql.Identifier("NAMA_KONSUMER")
        kuota = sql.Identifier("KUOTA")
        max_kuota = sql.Identifier("MAX_KUOTA")
        conflict = sql.Identifier("CONFLICT")
        status_code = sql.Identifier("STATUS_CODE")
        status_code_description = sql.Identifier("STATUS_CODE_DESCRIPTION")
        problem = sql.Identifier("PROBLEM")
        last_transaction_time = sql.Identifier("LAST_TRANSACTION_TIME")
        previous_transaction_time = sql.Identifier("PREVIOUS_TRANSACTION_TIME")
        updated_time = sql.Identifier("UPDATED_TIME")
        created_time = sql.Identifier("CREATED_TIME")

        next_kuota = sql.SQL(
            """
            CASE
                WHEN EXCLUDED.{updated_time} <= target.{updated_time}
                    THEN target.{kuota}
                WHEN date_trunc('month', target.{updated_time})
                     < date_trunc('month', EXCLUDED.{updated_time})
                    THEN EXCLUDED.{kuota}
                WHEN EXCLUDED.{kuota} > 0
                    THEN target.{kuota} + EXCLUDED.{kuota}
                ELSE target.{kuota}
            END
            """
        ).format(updated_time=updated_time, kuota=kuota)

        next_max_kuota = sql.SQL(
            """
            CASE
                WHEN EXCLUDED.{updated_time} <= target.{updated_time}
                    THEN target.{max_kuota}
                WHEN EXCLUDED.{kuota} > 0
                    THEN GREATEST(target.{max_kuota}, {next_kuota})
                ELSE GREATEST(target.{max_kuota}, target.{kuota})
            END
            """
        ).format(
            updated_time=updated_time,
            max_kuota=max_kuota,
            kuota=kuota,
            next_kuota=next_kuota,
        )

        next_last_transaction_time = sql.SQL(
            """
            CASE
                WHEN EXCLUDED.{updated_time} <= target.{updated_time}
                    THEN target.{last_transaction_time}
                WHEN EXCLUDED.{kuota} > 0
                    THEN EXCLUDED.{last_transaction_time}
                ELSE target.{last_transaction_time}
            END
            """
        ).format(
            updated_time=updated_time,
            kuota=kuota,
            last_transaction_time=last_transaction_time,
        )

        next_previous_transaction_time = sql.SQL(
            """
            CASE
                WHEN EXCLUDED.{updated_time} <= target.{updated_time}
                    THEN target.{previous_transaction_time}
                WHEN EXCLUDED.{kuota} > 0
                    THEN COALESCE(
                        target.{last_transaction_time},
                        CASE
                            WHEN target.{kuota} > 0 THEN target.{updated_time}
                            ELSE target.{previous_transaction_time}
                        END
                    )
                ELSE target.{previous_transaction_time}
            END
            """
        ).format(
            updated_time=updated_time,
            kuota=kuota,
            last_transaction_time=last_transaction_time,
            previous_transaction_time=previous_transaction_time,
        )

        return sql.SQL(
            """
            INSERT INTO {table} AS target (
                {operator},
                {nik},
                {nama_konsumer},
                {kuota},
                {max_kuota},
                {conflict},
                {status_code},
                {status_code_description},
                {problem},
                {last_transaction_time},
                {previous_transaction_time},
                {updated_time},
                {created_time}
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT ({nik}) DO UPDATE SET
                {operator} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN EXCLUDED.{operator}
                    ELSE target.{operator}
                END,
                {nama_konsumer} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN EXCLUDED.{nama_konsumer}
                    ELSE target.{nama_konsumer}
                END,
                {kuota} = {next_kuota},
                {max_kuota} = {next_max_kuota},
                {conflict} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN EXCLUDED.{conflict}
                    ELSE target.{conflict}
                END,
                {status_code} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN EXCLUDED.{status_code}
                    ELSE target.{status_code}
                END,
                {status_code_description} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN EXCLUDED.{status_code_description}
                    ELSE target.{status_code_description}
                END,
                {problem} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN EXCLUDED.{problem}
                    ELSE target.{problem}
                END,
                {last_transaction_time} = {next_last_transaction_time},
                {previous_transaction_time} = {next_previous_transaction_time},
                {updated_time} = GREATEST(target.{updated_time}, EXCLUDED.{updated_time})
            """
        ).format(
            table=table,
            operator=operator,
            nik=nik,
            nama_konsumer=nama_konsumer,
            kuota=kuota,
            max_kuota=max_kuota,
            conflict=conflict,
            status_code=status_code,
            status_code_description=status_code_description,
            problem=problem,
            last_transaction_time=last_transaction_time,
            previous_transaction_time=previous_transaction_time,
            updated_time=updated_time,
            created_time=created_time,
            next_kuota=next_kuota,
            next_max_kuota=next_max_kuota,
            next_last_transaction_time=next_last_transaction_time,
            next_previous_transaction_time=next_previous_transaction_time,
        )


def read_report_payloads(path: Path) -> Iterable[Mapping[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        yield from _read_jsonl_report(path)
        return

    if suffix == ".csv":
        yield from _read_csv_report(path)
        return

    if suffix == ".json":
        yield from _read_json_report(path)
        return

    raise ValueError(f"Unsupported report file type: {path.suffix}")


def _read_jsonl_report(path: Path) -> Iterable[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8") as file_handle:
        for line in file_handle:
            stripped = line.strip()
            if stripped:
                payload = json.loads(stripped)
                if isinstance(payload, Mapping):
                    yield payload


def _read_csv_report(path: Path) -> Iterable[Mapping[str, Any]]:
    with path.open("r", newline="", encoding="utf-8") as file_handle:
        yield from csv.DictReader(file_handle)


def _read_json_report(path: Path) -> Iterable[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("items") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        raise ValueError(  # noqa: TRY004 - malformed report content is a value error.
            "JSON report must be a list or contain an 'items' list."
        )

    for row in rows:
        if isinstance(row, Mapping):
            yield row


def format_db_datetime(value: datetime) -> str:
    return _normalize_datetime(value).strftime(TIMESTAMP_FORMAT)


def _normalize_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized or _DEFAULT_STATUS


def _map_report_status(status: str) -> ReportStatusMapping:
    mapping = _STATUS_MAPPINGS.get(status)
    if mapping is not None:
        return mapping
    if status.startswith("skipped_"):
        return _DEFAULT_SKIPPED_MAPPING
    if status == "error" or "error" in status:
        return _DEFAULT_ERROR_MAPPING
    return _DEFAULT_UNKNOWN_MAPPING


def _build_problem(payload: Mapping[str, Any]) -> str:
    status = _normalize_status(payload.get("status"))
    reason = str(payload.get("reason", "")).strip()
    error_label = str(payload.get("error_label", "")).strip()
    error = str(payload.get("error", "")).strip()

    details = [part for part in (reason, error_label, error) if part]
    if details:
        return f"{status}: {' | '.join(details)}" if status else " | ".join(details)
    return status or "failed"


def _extract_name(payload: Mapping[str, Any]) -> str:
    for field_name in _NAME_FIELDS:
        value = payload.get(field_name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _parse_nik(value: Any) -> int:
    if value is None:
        raise ValueError("Report row is missing NIK.")

    normalized = str(value).strip()
    if not normalized.isdigit():
        raise ValueError(f"NIK must be numeric: {value!r}")

    return int(normalized)


def _parse_report_datetime(value: Any) -> datetime:
    if value is None or not str(value).strip():
        return _normalize_datetime(datetime.now().astimezone())

    raw_value = str(value).strip()
    for parser in (
        datetime.fromisoformat,
        lambda text: datetime.strptime(text, TIMESTAMP_FORMAT).astimezone(),
    ):
        try:
            return _normalize_datetime(parser(raw_value))
        except ValueError:
            continue

    return _normalize_datetime(datetime.now().astimezone())


def _coerce_db_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    return _parse_report_datetime(value)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _normalize_table_name(value: str) -> str:
    normalized = value.strip().upper()
    if _OPERATOR_TABLE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"Unsupported operator table: {value}")
    return normalized


def _collect_operator_suffixes(source: Mapping[str, str]) -> set[str]:
    suffixes: set[str] = set()
    for key in source:
        match = _NUMBERED_TARGET_KEY_PATTERN.fullmatch(key)
        if match is not None:
            suffixes.add(match.group(1) or match.group(2))
    return suffixes


def _normalize_key(value: str) -> str:
    return value.strip().lower()


def _dedupe_nonempty(values: Iterable[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = _normalize_key(normalized)
        if normalized and key not in seen:
            deduped.append(normalized)
            seen.add(key)
    return tuple(deduped)
