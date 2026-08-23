# ruff: noqa: DTZ001

from datetime import datetime

import pytest

import src.infrastructure.database.operator_store as operator_store_module
from src.infrastructure.database.operator_store import (
    DatabaseConfig,
    OperatorDatabaseManager,
    OperatorDbRecord,
    OperatorTargets,
    format_db_datetime,
    read_report_payloads,
)


def test_database_config_loads_required_env_values():
    config = DatabaseConfig.from_env(
        {
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
            "DB_NAME": "taskbot",
            "DB_USER": "taskbot_user",
            "DB_PASSWORD": "secret",
        },
        load_env_file=False,
    )

    assert config.host == "localhost"
    assert config.port == 5432
    assert config.name == "taskbot"
    assert config.user == "taskbot_user"
    assert config.password == "secret"
    assert config.maintenance_name == "postgres"


def test_database_config_registers_password_as_private(monkeypatch):
    registered_values = []
    monkeypatch.setattr(
        operator_store_module,
        "register_private_values",
        lambda *values: registered_values.extend(values),
    )

    DatabaseConfig.from_env(
        {
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
            "DB_NAME": "taskbot",
            "DB_USER": "taskbot_user",
            "DB_PASSWORD": "database-secret",
        },
        load_env_file=False,
    )

    assert registered_values == ["database-secret"]


def test_operator_targets_resolve_by_name_email_and_forced_table():
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "First Operator",
            "EMAIL_1": "first@example.com",
            "OPERATOR_1_ID": "primary-terminal",
            "NAME_OPERATORS_2": "Second Operator",
            "EMAIL_2": "second@example.com",
        },
        load_env_file=False,
    )

    assert targets.resolve("First Operator").table_name == "OPERATOR_1"
    assert targets.resolve("first@example.com").table_name == "OPERATOR_1"
    assert targets.resolve("primary-terminal").table_name == "OPERATOR_1"
    assert targets.resolve("primary-terminal").operator_id == "primary-terminal"
    assert targets.resolve("second@example.com").table_name == "OPERATOR_2"
    assert targets.resolve("operator_02").table_name == "OPERATOR_2"
    assert targets.resolve("operator_02").operator_id == "operator_02"
    assert (
        targets.resolve("", table_name="OPERATOR_2").operator_name == "Second Operator"
    )


def test_operator_targets_support_one_configured_account():
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "Only Operator",
            "EMAIL_1": "only@example.com",
            "PIN_1": "123456",
            "NIK_1": "1001,1002",
        },
        load_env_file=False,
    )

    assert len(targets.targets) == 1
    assert targets.targets[0].table_name == "OPERATOR_1"
    assert targets.targets[0].operator_name == "Only Operator"
    assert targets.targets[0].operator_id == "operator_01"
    assert targets.resolve("only@example.com") == targets.targets[0]
    assert targets.resolve("operator_01") == targets.targets[0]


def test_operator_targets_map_legacy_single_account_to_first_table():
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "Legacy Operator",
            "EMAIL": "legacy@example.com",
            "PIN": "123456",
            "NIK": "1001,1002",
            "OPERATOR_ID": "legacy-terminal",
        },
        load_env_file=False,
    )

    assert len(targets.targets) == 1
    assert targets.targets[0].table_name == "OPERATOR_1"
    assert targets.targets[0].operator_name == "Legacy Operator"
    assert targets.targets[0].operator_id == "legacy-terminal"
    assert targets.resolve("legacy@example.com") == targets.targets[0]
    assert targets.resolve("legacy-terminal") == targets.targets[0]


def test_operator_targets_discover_arbitrary_numbered_suffixes():
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_10": "Tenth Operator",
            "EMAIL_10": "tenth@example.com",
            "OPERATOR_10_ID": "operator-ten",
            "NAME_OPERATORS_3": "Third Operator",
            "EMAIL_3": "third@example.com",
        },
        load_env_file=False,
    )

    assert [target.table_name for target in targets.targets] == [
        "OPERATOR_3",
        "OPERATOR_10",
    ]
    assert [target.operator_id for target in targets.targets] == [
        "operator_03",
        "operator-ten",
    ]
    assert targets.resolve("third@example.com").table_name == "OPERATOR_3"
    assert targets.resolve("operator-ten").table_name == "OPERATOR_10"
    assert (
        targets.resolve("", table_name="operator_10").operator_name
        == "Tenth Operator"
    )


@pytest.mark.parametrize(
    "partial_second_target",
    (
        {"EMAIL_2": "second@example.com"},
        {"PIN_2": "654321"},
        {"NIK_2": "2002"},
        {"OPERATOR_2_ID": "secondary-terminal"},
    ),
)
def test_operator_targets_reject_partial_configured_account(partial_second_target):
    environ = {
        "NAME_OPERATORS_1": "First Operator",
        "EMAIL_1": "first@example.com",
        **partial_second_target,
    }

    with pytest.raises(ValueError, match="Missing NAME_OPERATORS_2"):
        OperatorTargets.from_env(environ, load_env_file=False)


def test_operator_targets_require_at_least_one_configured_account():
    with pytest.raises(ValueError, match="No operator targets configured"):
        OperatorTargets.from_env({}, load_env_file=False)


def test_operator_targets_reject_duplicate_stable_ids():
    with pytest.raises(ValueError, match="Operator IDs must be unique"):
        OperatorTargets.from_env(
            {
                "NAME_OPERATORS_1": "First Operator",
                "OPERATOR_1_ID": "shared-terminal",
                "NAME_OPERATORS_2": "Second Operator",
                "OPERATOR_2_ID": "SHARED-TERMINAL",
            },
            load_env_file=False,
        )


def test_operator_record_from_successful_report_maps_operator_and_status():
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "First Operator",
            "EMAIL_1": "first@example.com",
            "NAME_OPERATORS_2": "Second Operator",
        },
        load_env_file=False,
    )
    target = targets.resolve("first@example.com")

    record = OperatorDbRecord.from_report_payload(
        {
            "operator": "first@example.com",
            "nik": "001234",
            "status": "completed",
            "finished_at": "20260525 101112",
        },
        target,
    )

    assert record.nik == 1234
    assert record.operator == "First Operator"
    assert record.nama_konsumer == ""
    assert record.kuota_delta == 1
    assert record.status_code == 200
    assert record.status_code_description == "Transaction successful"
    assert record.conflict is False
    assert record.problem == ""
    assert format_db_datetime(record.event_time) == "20260525 101112"


def test_operator_record_from_failed_report_updates_problem_and_conflict():
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "First Operator",
            "NAME_OPERATORS_2": "Second Operator",
        },
        load_env_file=False,
    )
    target = targets.resolve("OPERATOR_1")

    record = OperatorDbRecord.from_report_payload(
        {
            "operator": "OPERATOR_1",
            "nik": "1234",
            "status": "skipped_max_kuota",
            "reason": "Max kuota before cek pesanan",
            "error_label": "application",
            "finished_at": "20260525 101112",
        },
        target,
    )

    assert record.kuota_delta == 0
    assert record.status_code == 409
    assert record.status_code_description == "Max kuota reached"
    assert record.conflict is True
    assert (
        record.problem
        == "skipped_max_kuota: Max kuota before cek pesanan | application"
    )
    assert format_db_datetime(record.event_time) == "20260525 101112"


def test_registration_request_limit_maps_to_http_429_without_kuota_delta():
    targets = OperatorTargets.from_env(
        {"NAME_OPERATORS_1": "First Operator"},
        load_env_file=False,
    )
    target = targets.resolve("operator_01")
    reason = (
        "Terlalu banyak melakukan permintaan pendaftaran untuk NIK pelanggan "
        "ini. Silakan coba lagi di hari berikutnya."
    )

    record = OperatorDbRecord.from_report_payload(
        {
            "operator_id": "operator_01",
            "nik": "1234",
            "status": "skipped_registration_request_limited",
            "reason": reason,
        },
        target,
    )

    assert record.kuota_delta == 0
    assert record.status_code == 429
    assert (
        record.status_code_description
        == "Consumer registration request limit reached"
    )
    assert record.conflict is True
    assert record.problem == f"skipped_registration_request_limited: {reason}"


def test_operator_record_uses_consumer_name_when_report_contains_it():
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "First Operator",
            "NAME_OPERATORS_2": "Second Operator",
        },
        load_env_file=False,
    )
    target = targets.resolve("OPERATOR_1")

    record = OperatorDbRecord.from_report_payload(
        {
            "operator": "OPERATOR_1",
            "nik": "1234",
            "status": "completed",
            "customer_name": "Consumer Name",
        },
        target,
    )

    assert record.operator == "First Operator"
    assert record.nama_konsumer == "Consumer Name"


def test_report_payload_reader_supports_jsonl_csv_and_snapshot_json(tmp_path):
    jsonl_path = tmp_path / "items.jsonl"
    jsonl_path.write_text(
        '{"nik": "1", "status": "completed"}\n{"nik": "2", "status": "error"}\n',
        encoding="utf-8",
    )
    assert [row["nik"] for row in read_report_payloads(jsonl_path)] == ["1", "2"]

    csv_path = tmp_path / "items.csv"
    csv_path.write_text("nik,status\n3,completed\n", encoding="utf-8")
    assert list(read_report_payloads(csv_path)) == [{"nik": "3", "status": "completed"}]

    snapshot_path = tmp_path / "items_snapshot.json"
    snapshot_path.write_text(
        '{"items": [{"nik": "4", "status": "completed"}]}',
        encoding="utf-8",
    )
    assert list(read_report_payloads(snapshot_path)) == [
        {"nik": "4", "status": "completed"}
    ]


def test_upsert_record_passes_expected_values_to_cursor():
    class FakeCursor:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params):
            self.calls.append((statement, params))

        def fetchone(self):
            return None

    cursor = FakeCursor()
    manager = OperatorDatabaseManager(
        DatabaseConfig(
            host="localhost",
            port=5432,
            name="taskbot",
            user="taskbot",
            password="secret",
        )
    )
    event_time = datetime(2026, 5, 25, 10, 11, 12)
    record = OperatorDbRecord(
        operator="First Operator",
        nik=1234,
        nama_konsumer="Consumer Name",
        kuota_delta=1,
        status_code=200,
        status_code_description="Transaction successful",
        problem="",
        conflict=False,
        event_time=event_time,
    )

    manager.upsert_record("OPERATOR_1", record, cursor=cursor)

    assert len(cursor.calls) == 2
    assert cursor.calls[0][1] == (1234,)
    _statement, params = cursor.calls[1]
    assert params == (
        "First Operator",
        1234,
        "Consumer Name",
        1,
        1,
        False,
        200,
        "Transaction successful",
        "",
        event_time,
        None,
        event_time,
        event_time,
    )


def test_sync_report_payloads_only_writes_the_supplied_batch():
    class FakeCursor:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params):
            self.calls.append((statement, params))

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()

        def cursor(self):
            return self.cursor_instance

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "First Operator",
            "EMAIL_1": "first@example.com",
            "NAME_OPERATORS_2": "Second Operator",
            "EMAIL_2": "second@example.com",
        },
        load_env_file=False,
    )
    manager = OperatorDatabaseManager(
        DatabaseConfig(
            host="localhost",
            port=5432,
            name="taskbot",
            user="taskbot",
            password="secret",
        ),
        targets=targets,
    )
    connection = FakeConnection()
    manager._connect = lambda database_name: connection

    summary = manager.sync_report_payloads(
        (
            {
                "operator": "first@example.com",
                "nik": "1001",
                "status": "completed",
                "finished_at": "20260525 101112",
            },
            {
                "operator": "second@example.com",
                "nik": "2002",
                "status": "error",
                "finished_at": "20260525 101113",
            },
        ),
        source="operator-batch",
    )

    assert summary.source == "operator-batch"
    assert summary.processed == 2
    assert summary.inserted_or_updated == 2
    assert summary.skipped == 0
    assert [params for _statement, params in connection.cursor_instance.calls] == [
        (1001,),
        (
            "First Operator",
            1001,
            "",
            1,
            1,
            False,
            200,
            "Transaction successful",
            "",
            datetime(2026, 5, 25, 10, 11, 12),
            None,
            datetime(2026, 5, 25, 10, 11, 12),
            datetime(2026, 5, 25, 10, 11, 12),
        ),
        (
            "Second Operator",
            2002,
            "",
            0,
            0,
            True,
            500,
            "Transaction error",
            "error",
            None,
            None,
            datetime(2026, 5, 25, 10, 11, 13),
            datetime(2026, 5, 25, 10, 11, 13),
        ),
    ]


def test_database_sync_telemetry_uses_stable_operator_id(monkeypatch):
    log_contexts = []

    class CapturingLogger:
        def bind(self, **context):
            log_contexts.append(context)
            return self

        def debug(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def exception(self, *_args, **_kwargs):
            return None

    class FakeCursor:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params):
            self.calls.append((statement, params))

        def fetchone(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.closed = False

        def cursor(self):
            return self.cursor_instance

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(operator_store_module, "logger", CapturingLogger())
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "First Operator",
            "EMAIL_1": "first@example.com",
            "OPERATOR_1_ID": "primary-terminal",
        },
        load_env_file=False,
    )
    manager = OperatorDatabaseManager(
        DatabaseConfig(
            host="localhost",
            port=5432,
            name="taskbot",
            user="taskbot",
            password="secret",
        ),
        targets=targets,
    )
    connection = FakeConnection()
    manager._connect = lambda database_name: connection

    summary = manager.sync_report_payloads(
        (
            {
                "operator_id": "primary-terminal",
                "operator": "<redacted-email>",
                "nik": "1001",
                "status": "completed",
                "finished_at": "20260525 101112",
            },
            {
                "operator_id": "primary-terminal",
                "operator": "<redacted-email>",
                "nik": "invalid",
                "status": "completed",
                "finished_at": "20260525 101113",
            },
        ),
        source="operator-id-telemetry",
    )

    assert summary.processed == 2
    assert summary.inserted_or_updated == 1
    assert summary.skipped == 1
    events = {context["event"]: context for context in log_contexts}
    for event_name in (
        "database.report_sync.started",
        "database.report_sync.row_upserted",
        "database.report_sync.row_skipped",
        "database.report_sync.finished",
    ):
        assert events[event_name]["operator_id"] == "primary-terminal"
        assert events[event_name]["operator_ids"] == ["primary-terminal"]

    upsert_params = connection.cursor_instance.calls[1][1]
    assert upsert_params[0] == "First Operator"


def test_successful_repeat_reports_previous_transaction_time_to_sync_summary(tmp_path):
    class FakeCursor:
        def __init__(self):
            self.calls = []
            self.previous_transaction_row = (
                datetime(2026, 5, 20, 8, 30, 0),
                datetime(2026, 5, 20, 8, 30, 0),
                1,
            )

        def execute(self, statement, params):
            self.calls.append((statement, params))

        def fetchone(self):
            return self.previous_transaction_row

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()

        def cursor(self):
            return self.cursor_instance

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_1": "First Operator",
            "EMAIL_1": "first@example.com",
            "NAME_OPERATORS_2": "Second Operator",
        },
        load_env_file=False,
    )
    manager = OperatorDatabaseManager(
        DatabaseConfig(
            host="localhost",
            port=5432,
            name="taskbot",
            user="taskbot",
            password="secret",
        ),
        targets=targets,
    )
    connection = FakeConnection()
    manager._connect = lambda database_name: connection
    jsonl_path = tmp_path / "items.jsonl"
    jsonl_path.write_text(
        (
            '{"operator": "first@example.com", "nik": "1234", '
            '"status": "completed", "finished_at": "20260525 101112"}\n'
        ),
        encoding="utf-8",
    )

    summary = manager.sync_report_file(jsonl_path)

    assert summary.processed == 1
    assert summary.inserted_or_updated == 1
    assert summary.skipped == 0
    assert len(summary.previous_transactions) == 1
    previous = summary.previous_transactions[0]
    assert previous.table_name == "OPERATOR_1"
    assert previous.operator == "First Operator"
    assert previous.nik == 1234
    assert format_db_datetime(previous.previous_transaction_time) == "20260520 083000"
    assert format_db_datetime(previous.current_transaction_time) == "20260525 101112"
    assert previous.kuota_before == 1

    _select_call, upsert_call = connection.cursor_instance.calls
    assert _select_call[1] == (1234,)
    assert upsert_call[1][3] == 1
    assert upsert_call[1][9] == datetime(2026, 5, 25, 10, 11, 12)
    assert upsert_call[1][10] == datetime(2026, 5, 20, 8, 30, 0)


def test_migrate_table_schema_moves_old_nama_to_operator_and_adds_new_columns():
    class FakeCursor:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params=None):
            self.calls.append((statement, params))

        def fetchall(self):
            return [
                ("NIK",),
                ("NAMA",),
                ("KUOTA",),
                ("MAX_KUOTA",),
                ("CONFLICT",),
                ("PROBLEM",),
                ("UPDATED_TIME",),
                ("CREATED_TIME",),
            ]

    cursor = FakeCursor()

    OperatorDatabaseManager._migrate_table_schema(cursor, "OPERATOR_1")

    assert cursor.calls[0][1] == ("OPERATOR_1",)
    assert len(cursor.calls) == 8


def test_manager_uses_configured_dynamic_tables_for_setup_reset_and_logging(
    monkeypatch,
):
    log_contexts = []

    class CapturingLogger:
        def bind(self, **context):
            log_contexts.append(context)
            return self

        def debug(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def exception(self, *_args, **_kwargs):
            return None

    class FakeCursor:
        rowcount = 2

        def __init__(self):
            self.calls = []

        def execute(self, statement, params=None):
            self.calls.append((statement, params))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()

        def cursor(self):
            return self.cursor_instance

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(operator_store_module, "logger", CapturingLogger())
    created_tables = []
    migrated_tables = []
    monkeypatch.setattr(
        OperatorDatabaseManager,
        "_create_table_sql",
        staticmethod(lambda table_name: created_tables.append(table_name)),
    )
    monkeypatch.setattr(
        OperatorDatabaseManager,
        "_migrate_table_schema",
        staticmethod(
            lambda _cursor, table_name: migrated_tables.append(table_name)
        ),
    )
    targets = OperatorTargets.from_env(
        {
            "NAME_OPERATORS_3": "Third Operator",
            "EMAIL_3": "third@example.com",
            "NAME_OPERATORS_10": "Tenth Operator",
            "EMAIL_10": "tenth@example.com",
        },
        load_env_file=False,
    )
    manager = OperatorDatabaseManager(
        DatabaseConfig(
            host="localhost",
            port=5432,
            name="taskbot",
            user="taskbot",
            password="secret",
        ),
        targets=targets,
    )
    connection = FakeConnection()
    manager._connect = lambda _database_name: connection
    reference_time = datetime(2026, 6, 1, 0, 0, 0)

    manager.ensure_tables_exist()
    manager.reset_monthly_quotas(reference_time)

    assert created_tables == ["OPERATOR_3", "OPERATOR_10"]
    assert migrated_tables == ["OPERATOR_3", "OPERATOR_10"]
    assert [
        params
        for _statement, params in connection.cursor_instance.calls
        if params is not None
    ] == [(reference_time,), (reference_time,)]

    events = {context["event"]: context for context in log_contexts}
    assert events["database.tables.ensure.started"]["tables"] == [
        "OPERATOR_3",
        "OPERATOR_10",
    ]
    assert events["database.monthly_quota_reset.started"]["tables"] == [
        "OPERATOR_3",
        "OPERATOR_10",
    ]
    per_table_setup = [
        context
        for context in log_contexts
        if context["event"] == "database.table.ensure.started"
    ]
    assert [context["operator_id"] for context in per_table_setup] == [
        "operator_03",
        "operator_10",
    ]
    per_table_reset = [
        context
        for context in log_contexts
        if context["event"] == "database.monthly_quota_reset.table_finished"
    ]
    assert [context["table_name"] for context in per_table_reset] == [
        "OPERATOR_3",
        "OPERATOR_10",
    ]


def test_manager_without_required_targets_keeps_default_tables():
    manager = OperatorDatabaseManager.from_env(
        {
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
            "DB_NAME": "taskbot",
            "DB_USER": "taskbot_user",
            "DB_PASSWORD": "secret",
            "NAME_OPERATORS_10": "Ignored Operator",
        },
        load_env_file=False,
        require_operator_targets=False,
    )

    assert manager.targets is None
    assert manager._operator_table_names() == ("OPERATOR_1", "OPERATOR_2")


def test_operator_table_names_reject_unsafe_identifiers():
    OperatorDatabaseManager._create_table_sql("OPERATOR_42")

    with pytest.raises(ValueError, match="Unsupported operator table"):
        OperatorDatabaseManager._create_table_sql("OPERATOR_3; DROP TABLE users")


def test_monthly_reset_only_resets_kuota_without_bumping_updated_time():
    class FakeCursor:
        def __init__(self):
            self.calls = []

        def execute(self, statement, params):
            self.calls.append((statement, params))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()

        def cursor(self):
            return self.cursor_instance

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    manager = OperatorDatabaseManager(
        DatabaseConfig(
            host="localhost",
            port=5432,
            name="taskbot",
            user="taskbot",
            password="secret",
        )
    )
    connection = FakeConnection()
    manager._connect = lambda database_name: connection
    reference_time = datetime(2026, 6, 1, 0, 0, 0)

    manager.reset_monthly_quotas(reference_time)

    assert len(connection.cursor_instance.calls) == 2
    assert [params for _statement, params in connection.cursor_instance.calls] == [
        (reference_time,),
        (reference_time,),
    ]
