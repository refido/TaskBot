from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.infrastructure.interaction_diagnostics as diagnostics_module
from src.infrastructure.interaction_diagnostics import (
    InteractionDiagnostics,
    get_page_diagnostics,
    interaction_debug_enabled,
    interaction_pause_enabled,
    sanitize_diagnostic_text,
    sanitize_diagnostic_url,
)
from src.privacy import set_nik_masking


class RecordingLogger:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def bind(self, **fields):
        return BoundRecordingLogger(self, fields)


class BoundRecordingLogger:
    def __init__(self, owner: RecordingLogger, fields: dict) -> None:
        self.owner = owner
        self.fields = fields

    def info(self, message: str) -> None:
        self.owner.records.append({"level": "info", "message": message, **self.fields})

    def warning(self, message: str) -> None:
        self.owner.records.append(
            {"level": "warning", "message": message, **self.fields}
        )


class FakeTracing:
    def __init__(self) -> None:
        self.start_calls: list[dict] = []
        self.stop_calls: list[dict] = []

    def start(self, **kwargs) -> None:
        self.start_calls.append(kwargs)

    def stop(self, **kwargs) -> None:
        self.stop_calls.append(kwargs)


class FakeContext:
    def __init__(self) -> None:
        self.tracing = FakeTracing()
        self.listeners: dict[str, object] = {}

    def on(self, event: str, callback) -> None:
        self.listeners[event] = callback


class FakePage:
    def __init__(self, dom_state: dict | None = None) -> None:
        self.url = "https://app.test/customer?token=secret"
        self.dom_state = dom_state or {
            "dialogs": [],
            "buttons": [],
            "customer_type_radios": [],
        }
        self.waits: list[int] = []
        self.screenshots: list[dict] = []
        self.pause_calls = 0
        self.locator_queries: list[str] = []

    def evaluate(self, _script: str):
        return self.dom_state

    def locator(self, selector: str):
        self.locator_queries.append(selector)
        return SimpleNamespace(selector=selector)

    def screenshot(self, **kwargs) -> None:
        self.screenshots.append(kwargs)

    def wait_for_timeout(self, timeout_ms: int) -> None:
        self.waits.append(timeout_ms)

    def pause(self) -> None:
        self.pause_calls += 1


class FakeTarget:
    def __init__(self) -> None:
        self.hit_test_points: list[dict[str, float]] = []

    def evaluate(self, _script: str, arg=None, **_kwargs):
        if arg is None:
            return {"attached": True, "node_debug_id": "node-17"}
        self.hit_test_points.append(arg)
        return {
            "center": arg,
            "target_or_descendant_at_center": False,
            "top_element": {
                "tag": "div",
                "id": "overlay",
                "role": None,
                "class_name": "mantine-overlay",
                "text": "NIK 3573051108720003",
            },
        }

    def is_visible(self) -> bool:
        return True

    def is_enabled(self, **_kwargs) -> bool:
        return True

    def inner_text(self, **_kwargs) -> str:
        return "LANJUTKAN PENJUALAN"

    def get_attribute(self, name: str, **_kwargs):
        assert name == "aria-disabled"
        return "false"

    def bounding_box(self, **_kwargs):
        return {"x": 10.0, "y": 20.0, "width": 100.0, "height": 40.0}


class FakeTargetCollection:
    def __init__(self, *targets: FakeTarget) -> None:
        self.targets = targets

    def count(self) -> int:
        return len(self.targets)

    def nth(self, index: int) -> FakeTarget:
        return self.targets[index]


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        self.value += 0.05
        return self.value


@pytest.fixture
def recording_logger(monkeypatch):
    observed = RecordingLogger()
    monkeypatch.setattr(diagnostics_module, "logger", observed)
    return observed


def build_diagnostics(
    tmp_path,
    *,
    page: FakePage | None = None,
    context: FakeContext | None = None,
    pause_enabled: bool = False,
    monotonic=None,
) -> InteractionDiagnostics:
    return InteractionDiagnostics(
        page=page or FakePage(),
        context=context or FakeContext(),
        run_dir=tmp_path,
        operator_id="operator_01",
        pause_enabled=pause_enabled,
        monotonic=monotonic or FakeClock(),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", False),
        ("0", False),
        ("false", False),
        ("1", True),
        ("TRUE", True),
        ("on", True),
    ],
)
def test_debug_flags_parse_explicit_values(value: str, expected: bool):
    assert interaction_debug_enabled({"TASKBOT_INTERACTION_DEBUG": value}) is expected
    assert interaction_pause_enabled({"TASKBOT_INTERACTION_PAUSE": value}) is expected


def test_debug_flags_reject_typos():
    with pytest.raises(ValueError, match="TASKBOT_INTERACTION_DEBUG"):
        interaction_debug_enabled({"TASKBOT_INTERACTION_DEBUG": "enabled-ish"})


def test_diagnostic_sanitizers_always_remove_secrets_when_mask_is_disabled():
    set_nik_masking(False)
    try:
        text = sanitize_diagnostic_text(
            "NIK 3573051108720003 email user@example.com "
            "PIN=123456 token=top-secret abcdefgh.ijklmnop.qrstuvwx"
        )
        url = sanitize_diagnostic_url(
            "https://user:password@app.test/customer/3573051108720003"
            "?nik=3573051108720003&token=top-secret#fragment"
        )
    finally:
        set_nik_masking(True)

    combined = f"{text} {url}"
    for secret in (
        "3573051108720003",
        "user@example.com",
        "123456",
        "top-secret",
        "abcdefgh.ijklmnop.qrstuvwx",
        "password@",
        "fragment",
    ):
        assert secret not in combined
    assert "https://app.test/customer/<redacted-nik>?<redacted>" in url


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://example.test:bad/path?token=secret",
        "https://example.test:99999/path?token=secret",
        "data:text/plain,unlabelled-sensitive-value",
    ],
)
def test_diagnostic_url_sanitizer_is_total_and_redacts_unsafe_urls(unsafe_url: str):
    sanitized = sanitize_diagnostic_url(unsafe_url)

    assert "secret" not in sanitized
    assert "unlabelled-sensitive-value" not in sanitized


def test_diagnostic_text_redacts_formatted_nik_and_opaque_url_segments():
    assert "3573-0511-0872-0003" not in sanitize_diagnostic_text(
        "NIK 3573-0511-0872-0003"
    )
    url = sanitize_diagnostic_url(
        "https://app.test/api/auth/eyJhbGciOiJIUzI1NiJ9abcdefghi"
    )
    assert "eyJhbGciOiJIUzI1NiJ9abcdefghi" not in url


def test_dom_state_logs_every_required_control_without_raw_secrets(
    tmp_path,
    recording_logger,
):
    page = FakePage(
        {
            "dialogs": [
                {
                    "node_debug_id": "node-1",
                    "text": "Jenis Pelanggan untuk 3573051108720003",
                    "visible": True,
                }
            ],
            "buttons": [
                {
                    "node_debug_id": "node-2",
                    "text": "LANJUTKAN PENJUALAN",
                    "visible": True,
                    "enabled": True,
                    "disabled": False,
                    "aria_disabled": "false",
                    "bounding_box": {
                        "x": 10,
                        "y": 20,
                        "width": 100,
                        "height": 40,
                    },
                }
            ],
            "customer_type_radios": [
                {
                    "node_debug_id": "node-3",
                    "text": "Rumah Tangga",
                    "checked": True,
                    "disabled": False,
                    "value": "3573051108720003",
                    "name": "customer-type",
                }
            ],
        }
    )
    diagnostics = build_diagnostics(tmp_path, page=page)

    set_nik_masking(False)
    try:
        diagnostics.debug_interaction_state("customer_type_radio_confirmed")
    finally:
        set_nik_masking(True)

    events = [record["event"] for record in recording_logger.records]
    assert events == [
        "playwright.interaction.state",
        "playwright.interaction.dialog",
        "playwright.interaction.button",
        "playwright.interaction.radio",
    ]
    state_record = recording_logger.records[0]
    assert state_record["visible_dialog_count"] == 1
    assert state_record["visible_button_count"] == 1
    assert state_record["customer_type_radio_count"] == 1
    assert "3573051108720003" not in repr(recording_logger.records)
    assert "token=secret" not in repr(recording_logger.records)


def test_target_logging_captures_count_node_identity_and_center_hit_test(
    tmp_path,
    recording_logger,
):
    target = FakeTarget()
    diagnostics = build_diagnostics(tmp_path)

    diagnostics.debug_target_locator(
        "continue_before_click",
        "LANJUTKAN PENJUALAN",
        FakeTargetCollection(target),
    )

    summary = next(
        record
        for record in recording_logger.records
        if record["event"] == "playwright.interaction.target"
    )
    match = next(
        record
        for record in recording_logger.records
        if record["event"] == "playwright.interaction.target_match"
    )
    assert summary["locator_count"] == 1
    assert match["attached"] is True
    assert match["visible"] is True
    assert match["enabled"] is True
    assert match["node_debug_id"] == "node-17"
    assert match["bounding_box"] == {
        "x": 10.0,
        "y": 20.0,
        "width": 100.0,
        "height": 40.0,
    }
    assert target.hit_test_points == [{"x": 60.0, "y": 40.0}]
    assert match["element_from_point"]["target_or_descendant_at_center"] is False
    assert "3573051108720003" not in repr(match)


def test_polling_observes_full_twenty_seconds_and_logs_only_transitions(
    tmp_path,
    recording_logger,
):
    page = FakePage()
    diagnostics = build_diagnostics(tmp_path, page=page)
    observations = iter([False, False, True, *([True] * 78)])
    changes: list[tuple[str, bool | None, bool, int]] = []

    diagnostics.poll_state_changes(
        "continue_post_click_20s",
        {"transaction_form_visible": lambda: next(observations)},
        duration_ms=20_000,
        interval_ms=250,
        on_change=lambda *args: changes.append(args),
    )

    transition_records = [
        record
        for record in recording_logger.records
        if record["event"] == "playwright.interaction.state_change"
    ]
    assert page.waits == [250] * 80
    assert sum(page.waits) == 20_000
    assert [(item["previous"], item["current"]) for item in transition_records] == [
        (None, False),
        (False, True),
    ]
    assert changes == [
        ("transaction_form_visible", None, False, 0),
        ("transaction_form_visible", False, True, 500),
    ]


def test_repeated_probe_failure_is_logged_once_per_unchanged_error(
    tmp_path,
    recording_logger,
):
    page = FakePage()
    diagnostics = build_diagnostics(tmp_path, page=page)

    def failing_probe() -> bool:
        raise RuntimeError("DOM replaced")

    diagnostics.poll_state_changes(
        "failure_poll",
        {"continue_button_visible": failing_probe},
    )

    probe_failures = [
        record
        for record in recording_logger.records
        if record.get("operation") == "state_probe"
    ]
    assert len(probe_failures) == 1
    assert sum(page.waits) == 20_000


def test_screenshots_use_unique_safe_paths_mask_inputs_and_pause_when_enabled(
    tmp_path,
    recording_logger,
):
    page = FakePage()
    diagnostics = build_diagnostics(
        tmp_path,
        page=page,
        pause_enabled=True,
    )

    first = diagnostics.screenshot("nib Tutup/before click")
    second = diagnostics.screenshot("nib Tutup/before click")
    diagnostics.pause("nib_tutup_detected")

    assert first is not None and first.name == "0001_nib_Tutup_before_click.png"
    assert second is not None and second.name == "0002_nib_Tutup_before_click.png"
    assert page.screenshots[0]["full_page"] is True
    assert page.screenshots[0]["mask_color"] == "#000000"
    assert len(page.screenshots[0]["mask"]) == 1
    assert "input:not([type='radio'])" in page.locator_queries[0]
    assert page.pause_calls == 1
    assert any(
        record["event"] == "playwright.interaction.screenshot.saved"
        for record in recording_logger.records
    )


def test_operator_id_cannot_escape_the_run_artifact_tree(tmp_path):
    diagnostics = InteractionDiagnostics(
        page=FakePage(),
        context=FakeContext(),
        run_dir=tmp_path,
        operator_id="../../outside",
    )

    assert diagnostics.trace_path.is_relative_to(tmp_path)
    assert diagnostics.screenshot_dir.is_relative_to(tmp_path)
    assert ".." not in diagnostics.operator_id


def test_network_diagnostics_log_only_sanitized_metadata_and_timing(
    tmp_path,
    recording_logger,
):
    context = FakeContext()
    diagnostics = build_diagnostics(
        tmp_path,
        context=context,
        monotonic=FakeClock(),
    )
    diagnostics.start()
    request = SimpleNamespace(
        resource_type="fetch",
        method="POST",
        url=(
            "https://app.test/customer/3573051108720003"
            "?nik=3573051108720003&token=top-secret"
        ),
        timing={
            "startTime": 1.0,
            "requestStart": 2.0,
            "responseStart": 3.0,
            "responseEnd": 4.0,
        },
        failure="token=failed-secret",
        headers={"Authorization": "Bearer never-log-this"},
        post_data="PIN=123456",
    )
    response = SimpleNamespace(request=request, status=202)

    diagnostics.mark_phase("request_phase")
    context.listeners["request"](request)
    diagnostics.mark_phase("response_phase")
    context.listeners["response"](response)
    context.listeners["requestfinished"](request)
    failed_request = SimpleNamespace(
        **{**request.__dict__, "url": "https://app.test/fail?token=top-secret"}
    )
    context.listeners["request"](failed_request)
    context.listeners["requestfailed"](failed_request)
    pending_request = SimpleNamespace(
        **{**request.__dict__, "url": "https://app.test/pending?token=top-secret"}
    )
    context.listeners["request"](pending_request)
    diagnostics.stop(context_manager_failed=True)

    network_records = [
        record
        for record in recording_logger.records
        if record["event"].startswith("playwright.interaction.network.")
    ]
    rendered = repr(network_records)
    for secret in (
        "3573051108720003",
        "top-secret",
        "failed-secret",
        "never-log-this",
        "123456",
    ):
        assert secret not in rendered
    assert {record["event"] for record in network_records} >= {
        "playwright.interaction.network.request",
        "playwright.interaction.network.response",
        "playwright.interaction.network.finished",
        "playwright.interaction.network.failed",
        "playwright.interaction.network.pending",
    }
    assert "headers" not in rendered
    assert "post_data" not in rendered
    assert context.tracing.start_calls == [
        {"screenshots": True, "snapshots": True, "sources": True}
    ]
    assert context.tracing.stop_calls == [{"path": str(diagnostics.trace_path)}]
    response_record = next(
        record
        for record in network_records
        if record["event"] == "playwright.interaction.network.response"
    )
    assert response_record["phase"] == "request_phase"
    assert response_record["observed_phase"] == "response_phase"


def test_network_property_errors_never_escape_event_callbacks(
    tmp_path,
    recording_logger,
):
    class ExplodingRequest:
        @property
        def resource_type(self):
            raise RuntimeError("request channel closed")

    class ExplodingResponse:
        @property
        def request(self):
            raise RuntimeError("response channel closed")

    context = FakeContext()
    diagnostics = build_diagnostics(tmp_path, context=context)
    diagnostics.start()

    context.listeners["request"](ExplodingRequest())
    context.listeners["response"](ExplodingResponse())

    failures = [
        record
        for record in recording_logger.records
        if record["event"] == "playwright.interaction.diagnostic_failed"
    ]
    assert len(failures) == 2


def test_pending_log_failure_cannot_prevent_trace_stop_or_page_detach(
    tmp_path,
    recording_logger,
):
    page = FakePage()
    context = FakeContext()
    diagnostics = build_diagnostics(tmp_path, page=page, context=context)
    diagnostics.start()
    diagnostics._log_pending_requests = lambda: (_ for _ in ()).throw(
        RuntimeError("pending logger failed")
    )

    diagnostics.stop(context_manager_failed=True)

    assert context.tracing.stop_calls == [{"path": str(diagnostics.trace_path)}]
    assert get_page_diagnostics(page) is None
