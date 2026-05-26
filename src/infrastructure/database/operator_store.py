from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

OPERATOR_TABLE_NAMES = ("OPERATOR_1", "OPERATOR_2")
TIMESTAMP_FORMAT = "%Y%m%d %H%M%S"

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
    ) -> "DatabaseConfig":
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

        return cls(
            host=source["DB_HOST"].strip(),
            port=port,
            name=source["DB_NAME"].strip(),
            user=source["DB_USER"].strip(),
            password=source["DB_PASSWORD"],
            maintenance_name=source.get("DB_MAINTENANCE_NAME", "postgres").strip()
            or "postgres",
        )


@dataclass(frozen=True, slots=True)
class OperatorTarget:
    table_name: str
    operator_name: str
    aliases: tuple[str, ...] = ()

    def matches(self, operator: str) -> bool:
        normalized = _normalize_key(operator)
        return any(_normalize_key(alias) == normalized for alias in self.aliases)


@dataclass(frozen=True, slots=True)
class OperatorTargets:
    targets: tuple[OperatorTarget, ...]

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> "OperatorTargets":
        if load_env_file:
            load_dotenv()

        source = os.environ if environ is None else environ
        targets: list[OperatorTarget] = []
        for index, table_name in enumerate(OPERATOR_TABLE_NAMES, start=1):
            operator_name = source.get(f"NAME_OPERATORS_{index}", "").strip()
            if not operator_name:
                raise ValueError(f"Missing NAME_OPERATORS_{index}.")

            aliases = _dedupe_nonempty(
                (
                    operator_name,
                    source.get(f"EMAIL_{index}", ""),
                    table_name,
                )
            )
            targets.append(
                OperatorTarget(
                    table_name=table_name,
                    operator_name=operator_name,
                    aliases=aliases,
                )
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
            f"{target.table_name}={target.operator_name}" for target in self.targets
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
    ) -> "OperatorDbRecord":
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
class SyncSummary:
    source: str
    processed: int = 0
    inserted_or_updated: int = 0
    skipped: int = 0


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
    ) -> "OperatorDatabaseManager":
        config = DatabaseConfig.from_env(environ, load_env_file=load_env_file)
        targets = (
            OperatorTargets.from_env(environ, load_env_file=False)
            if require_operator_targets
            else None
        )
        return cls(config=config, targets=targets)

    def ensure_database_and_tables(self) -> None:
        self.ensure_database_exists()
        self.ensure_tables_exist()
        self.reset_monthly_quotas()

    def ensure_database_exists(self) -> None:
        connection = self._connect(self.config.maintenance_name)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s",
                    (self.config.name,),
                )
                if cursor.fetchone():
                    return

                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(self.config.name)
                    )
                )
        finally:
            connection.close()

    def ensure_tables_exist(self) -> None:
        with self._connect(self.config.name) as connection:
            with connection.cursor() as cursor:
                for table_name in OPERATOR_TABLE_NAMES:
                    cursor.execute(self._create_table_sql(table_name))
                    self._migrate_table_schema(cursor, table_name)

    def reset_monthly_quotas(self, reference_time: datetime | None = None) -> None:
        normalized_time = _normalize_datetime(
            reference_time or datetime.now().astimezone()
        )
        with self._connect(self.config.name) as connection:
            with connection.cursor() as cursor:
                for table_name in OPERATOR_TABLE_NAMES:
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

    def sync_report_file(
        self,
        report_path: str | Path,
        *,
        table_name: str | None = None,
    ) -> SyncSummary:
        path = Path(report_path)
        processed = 0
        changed = 0
        skipped = 0

        with self._connect(self.config.name) as connection:
            with connection.cursor() as cursor:
                for payload in read_report_payloads(path):
                    processed += 1
                    try:
                        self.upsert_report_payload(
                            payload,
                            cursor=cursor,
                            table_name=table_name,
                        )
                    except ValueError:
                        skipped += 1
                        continue
                    changed += 1

        return SyncSummary(
            source=str(path),
            processed=processed,
            inserted_or_updated=changed,
            skipped=skipped,
        )

    def upsert_report_payload(
        self,
        payload: Mapping[str, Any],
        *,
        cursor,
        table_name: str | None = None,
    ) -> None:
        if self.targets is None:
            raise ValueError("Operator targets are required to sync report payloads.")

        operator = str(payload.get("operator", "")).strip()
        target = self.targets.resolve(operator, table_name=table_name)
        record = OperatorDbRecord.from_report_payload(payload, target)
        self.upsert_record(target.table_name, record, cursor=cursor)

    def upsert_record(
        self, table_name: str, record: OperatorDbRecord, *, cursor
    ) -> None:
        normalized_table = _normalize_table_name(table_name)
        event_time = _normalize_datetime(record.event_time)
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
                event_time,
                event_time,
            ),
        )

    def _connect(self, database_name: str):
        return psycopg2.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=database_name,
            user=self.config.user,
            password=self.config.password,
        )

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
                "UPDATED_TIME",
                sql.SQL("TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ),
            (
                "CREATED_TIME",
                sql.SQL("TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"),
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
                {updated_time},
                {created_time}
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            updated_time=updated_time,
            created_time=created_time,
            next_kuota=next_kuota,
            next_max_kuota=next_max_kuota,
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
        raise ValueError("JSON report must be a list or contain an 'items' list.")

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
        lambda text: datetime.fromisoformat(text.replace("Z", "+00:00")),
        lambda text: datetime.strptime(text, TIMESTAMP_FORMAT),
    ):
        try:
            return _normalize_datetime(parser(raw_value))
        except ValueError:
            continue

    return _normalize_datetime(datetime.now().astimezone())


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _normalize_table_name(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in OPERATOR_TABLE_NAMES:
        raise ValueError(f"Unsupported operator table: {value}")
    return normalized


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
