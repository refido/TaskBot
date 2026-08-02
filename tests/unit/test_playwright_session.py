from types import SimpleNamespace

import pytest

import src.infrastructure.browser.playwright_session as playwright_session_module


@pytest.mark.parametrize("headless", [True, False])
def test_playwright_session_uses_configured_headless_mode(monkeypatch, headless: bool):
    launch_values: list[bool] = []

    class FakeBrowser:
        def new_context(self):
            return FakeContext()

        def close(self) -> None:
            return None

    class FakeContext:
        def new_page(self):
            return object()

        def close(self) -> None:
            return None

    class FakeFirefox:
        def launch(self, *, headless: bool):
            launch_values.append(headless)
            return FakeBrowser()

    class FakePlaywright:
        firefox = FakeFirefox()

        def stop(self) -> None:
            return None

    class FakePlaywrightStarter:
        def start(self):
            return FakePlaywright()

    monkeypatch.setattr(
        playwright_session_module,
        "sync_playwright",
        lambda: FakePlaywrightStarter(),
    )

    session = playwright_session_module.PlaywrightSession(
        SimpleNamespace(headless=headless)
    )
    with session:
        assert session.require_page() is not None

    assert launch_values == [headless]
