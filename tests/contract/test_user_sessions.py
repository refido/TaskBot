from pathlib import Path
from types import SimpleNamespace

import user_sessions
from src.application.use_cases import export_session as export_session_module
from src.infrastructure.sessions.export_service import SessionArtifacts


class DummyLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict, str]] = []
        self._bound: dict = {}

    def bind(self, **kwargs):
        self._bound = kwargs
        return self

    def info(self, message: str, *args, **kwargs) -> None:
        self.events.append(("info", self._bound.copy(), message))

    def exception(self, message: str, *args, **kwargs) -> None:
        self.events.append(("exception", self._bound.copy(), message))


def test_export_configured_sessions_limits_accounts_and_applies_cooldown():
    config = SimpleNamespace(
        account_configs=lambda: [
            SimpleNamespace(email_user="one@example.com"),
            SimpleNamespace(email_user="two@example.com"),
            SimpleNamespace(email_user="three@example.com"),
        ]
    )
    output_dir = Path("reports_phase6_contract")
    exported: list[tuple[str, Path]] = []
    cooldowns: list[float] = []
    log_print_calls: list[tuple[str, dict]] = []

    def exporter(account_config, output_dir: Path) -> SessionArtifacts:
        exported.append((account_config.email_user, output_dir))
        operator_slug = account_config.email_user.split("@", 1)[0]
        artifact_dir = output_dir / operator_slug
        profile_dir = artifact_dir / "profile"
        return SessionArtifacts(
            operator=account_config.email_user,
            artifact_dir=artifact_dir,
            profile_dir=profile_dir,
            cookie_count=2,
            xhr_count=3,
        )

    def fake_log_print(message: str, **kwargs) -> None:
        log_print_calls.append((message, kwargs))

    artifacts, failed_operators, resolved_output_dir = (
        export_session_module.export_configured_sessions(
            config,
            output_dir=output_dir,
            exporter=exporter,
            sleep_func=cooldowns.append,
            log=DummyLogger(),
            log_print_func=fake_log_print,
            max_account_hits=2,
            cooldown_seconds=5,
        )
    )

    assert resolved_output_dir == output_dir
    assert failed_operators == []
    assert [artifact.operator for artifact in artifacts] == [
        "one@example.com",
        "two@example.com",
    ]
    assert [email for email, _ in exported] == [
        "one@example.com",
        "two@example.com",
    ]
    assert cooldowns == [5]
    assert any(
        call[1].get("event") == "user_sessions.limit_applied"
        for call in log_print_calls
    )
    assert any(
        call[1].get("event") == "user_sessions.cooldown"
        for call in log_print_calls
    )
    assert any(
        call[1].get("event") == "user_sessions.summary.row"
        for call in log_print_calls
    )


def test_run_user_session_export_returns_one_when_any_export_fails():
    logger = DummyLogger()

    class FakeConfig:
        def account_configs(self):
            return [
                SimpleNamespace(email_user="one@example.com"),
                SimpleNamespace(email_user="two@example.com"),
            ]

    def exporter(account_config, output_dir: Path) -> SessionArtifacts:
        if account_config.email_user == "two@example.com":
            raise RuntimeError("capture failed")
        return SessionArtifacts(
            operator=account_config.email_user,
            artifact_dir=output_dir / "one",
            profile_dir=output_dir / "one" / "profile",
            cookie_count=1,
            xhr_count=1,
        )

    result = export_session_module.run_user_session_export(
        config_factory=FakeConfig,
        configure_logging_func=lambda app_name: {
            "run_id": "run-1",
            "json_log_path": "logs/run-1.jsonl",
        },
        exporter=exporter,
        sleep_func=lambda seconds: None,
        log=logger,
        log_print_func=lambda *args, **kwargs: None,
    )

    assert result == 1
    assert logger.events[0][1]["event"] == "user_sessions.start"
    assert any(
        event[1].get("event") == "user_session.failed" for event in logger.events
    )
    assert logger.events[-1][1]["event"] == "user_sessions.finished"
    assert logger.events[-1][1]["failure_count"] == 1


def test_user_sessions_main_delegates_to_packaged_use_case(monkeypatch):
    calls = {"count": 0}

    def fake_run_user_session_export() -> int:
        calls["count"] += 1
        return 7

    monkeypatch.setattr(
        user_sessions, "run_user_session_export", fake_run_user_session_export
    )

    assert user_sessions.main() == 7
    assert calls["count"] == 1


def test_user_sessions_reexports_session_export_surface():
    assert user_sessions.SessionArtifacts is SessionArtifacts
    assert (
        user_sessions.MAX_ACCOUNT_HITS_PER_RUN
        == export_session_module.MAX_ACCOUNT_HITS_PER_RUN
    )
    assert (
        user_sessions.INTER_ACCOUNT_COOLDOWN_SECONDS
        == export_session_module.INTER_ACCOUNT_COOLDOWN_SECONDS
    )
