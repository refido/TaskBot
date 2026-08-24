from __future__ import annotations

from types import SimpleNamespace

from src.application.services.session_recovery import SessionRecoveryService


def test_login_page_fallback_waits_via_retry_limiter_before_reauthentication():
    events: list[object] = []

    class FakePage:
        def goto(self, url: str) -> None:
            events.append(("goto", url))

        def wait_for_load_state(self, state: str) -> None:
            events.append(("load", state))

    class FakeDashboard:
        def ensure_on_dashboard(self) -> None:
            events.append("dashboard")

    class FakeLogin:
        def login(self, email: str, pin: str) -> None:
            events.append(("login", email, pin))

    class FakeLoginRetryRateLimiter:
        def wait_before_retry(self, page, account_key: str) -> None:
            events.append(("rate_limit", page, account_key))

    page = FakePage()
    service = SessionRecoveryService(
        page=page,
        config=SimpleNamespace(
            operator_id="operator_01",
            email_user="tester@example.com",
            pin_user="123456",
            url_application="https://app.test/",
        ),
        dashboard=FakeDashboard(),
        login=FakeLogin(),
        load_state="load",
        logged_out_check_timeout_ms=500,
        session_probe_interval_ms=1_000,
        login_page_detector=lambda *_args, **_kwargs: True,
        login_retry_rate_limiter=FakeLoginRetryRateLimiter(),
    )

    service.handle_session_recovery()

    assert events == [
        ("rate_limit", page, "operator_01"),
        ("goto", "https://app.test/"),
        ("load", "load"),
        ("login", "tester@example.com", "123456"),
        ("load", "load"),
        "dashboard",
    ]
