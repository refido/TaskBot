"""Build PostgreSQL statements for operator tables without opening a connection."""

import re

from psycopg2 import sql

_OPERATOR_TABLE_PATTERN = re.compile(r"^OPERATOR_\d+$")

COLUMN_NAMES = (
    "OPERATOR",
    "NIK",
    "NAMA_KONSUMER",
    "JENIS_PENGGUNA",
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


def normalize_table_name(value: str) -> str:
    normalized = value.strip().upper()
    if _OPERATOR_TABLE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"Unsupported operator table: {value}")
    return normalized


def create_table_sql(table_name: str):
    identifiers = {
        column_name.lower(): sql.Identifier(column_name) for column_name in COLUMN_NAMES
    }
    return sql.SQL(
        """
            CREATE TABLE IF NOT EXISTS {table} (
                {operator} TEXT NOT NULL DEFAULT '',
                {nik} BIGINT PRIMARY KEY,
                {nama_konsumer} TEXT NOT NULL DEFAULT '',
                {jenis_pengguna} TEXT NOT NULL DEFAULT '',
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
        table=sql.Identifier(normalize_table_name(table_name)),
        operator=identifiers["operator"],
        nik=identifiers["nik"],
        nama_konsumer=identifiers["nama_konsumer"],
        jenis_pengguna=identifiers["jenis_pengguna"],
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


def upsert_sql(table_name: str, *, distinct_sale: bool = False):
    table = sql.Identifier(normalize_table_name(table_name))
    operator = sql.Identifier("OPERATOR")
    nik = sql.Identifier("NIK")
    jenis_pengguna = sql.Identifier("JENIS_PENGGUNA")
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

    if distinct_sale:
        # The receipt already removed replays. Separate confirmed sales may
        # share a timestamp, or reach us behind a newer row in the same month.
        same_month = sql.SQL(
            "date_trunc('month', EXCLUDED.{t}) = date_trunc('month', target.{t})"
        ).format(t=updated_time)
        next_kuota = sql.SQL(
            "CASE WHEN {} THEN target.{} + EXCLUDED.{} ELSE {} END"
        ).format(same_month, kuota, kuota, next_kuota)
        next_max_kuota = sql.SQL("GREATEST(target.{}, {})").format(
            max_kuota, next_kuota
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

    if distinct_sale:
        # A late receipt may fall between the two stored sales. Preserve
        # the latest status while retaining the two latest sale times.
        next_last_transaction_time = sql.SQL(
            "GREATEST(target.{t}, EXCLUDED.{t})"
        ).format(t=last_transaction_time)
        next_previous_transaction_time = sql.SQL("""
                CASE WHEN EXCLUDED.{last} >= target.{last} THEN target.{last}
                     WHEN target.{last} IS NOT NULL THEN GREATEST(target.{prev}, EXCLUDED.{last})
                     WHEN target.{quota} > 0 AND target.{updated} < EXCLUDED.{last}
                         THEN target.{updated}
                     ELSE target.{prev} END
            """).format(
            last=last_transaction_time,
            prev=previous_transaction_time,
            quota=kuota,
            updated=updated_time,
        )

    return sql.SQL(
        """
            INSERT INTO {table} AS target (
                {operator},
                {nik},
                {nama_konsumer},
                {jenis_pengguna},
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
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT ({nik}) DO UPDATE SET
                {operator} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN EXCLUDED.{operator}
                    ELSE target.{operator}
                END,
                {jenis_pengguna} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN COALESCE(
                            NULLIF(EXCLUDED.{jenis_pengguna}, ''),
                            target.{jenis_pengguna}
                        )
                    ELSE target.{jenis_pengguna}
                END,
                {nama_konsumer} = CASE
                    WHEN EXCLUDED.{updated_time} > target.{updated_time}
                        THEN COALESCE(
                            NULLIF(EXCLUDED.{nama_konsumer}, ''),
                            target.{nama_konsumer}
                        )
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
        jenis_pengguna=jenis_pengguna,
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
