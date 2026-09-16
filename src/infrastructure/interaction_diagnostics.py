from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Locator, Page, Request, Response

from src.logging_utils import logger
from src.privacy import sanitize_text

_DEBUG_ENV = "TASKBOT_INTERACTION_DEBUG"
_PAUSE_ENV = "TASKBOT_INTERACTION_PAUSE"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"", "0", "false", "no", "off"})
_DIAGNOSTIC_NIK_PATTERN = re.compile(r"(?<!\d)(?:\d[\s.-]?){15}\d(?!\d)")
_DIAGNOSTIC_LONG_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{17,}(?!\d)")
_DIAGNOSTIC_JWT_PATTERN = re.compile(
    r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)
_DIAGNOSTIC_SECRET_PATTERN = re.compile(
    r"(?i)\b(pin|password|token|cookie|authorization|secret|session)\b"
    r"\s*[:=]\s*([^\s,;]+)"
)
_DIAGNOSTIC_SECRET_PATH_PATTERN = re.compile(
    r"(?i)(/(?:pin|password|token|cookie|authorization|auth|bearer|secret|"
    r"session|nik|access[_-]?key|api[_-]?key)"
    r"(?:/|=))([^/?#]+)"
)
_DIAGNOSTIC_OPAQUE_PATH_PATTERN = re.compile(r"(?<=/)[A-Za-z0-9_.-]{24,}(?=/|$)")
_URL_IN_TEXT_PATTERN = re.compile(r"https?://[^\s)\]}]+", re.IGNORECASE)
_SAFE_LABEL_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
_NETWORK_RESOURCE_TYPES = frozenset({"fetch", "xhr"})
_PAGE_DIAGNOSTICS_ATTRIBUTE = "_taskbot_interaction_diagnostics"
_LOCATOR_PROBE_TIMEOUT_MS = 500

_DOM_STATE_SCRIPT = r"""
() => {
  const root = window;
  if (!root.__taskbotInteractionNodeIds) {
    root.__taskbotInteractionNodeIds = new WeakMap();
    root.__taskbotInteractionNodeSequence = 0;
  }

  const nodeId = (element) => {
    let identifier = root.__taskbotInteractionNodeIds.get(element);
    if (!identifier) {
      root.__taskbotInteractionNodeSequence += 1;
      identifier = `node-${root.__taskbotInteractionNodeSequence}`;
      root.__taskbotInteractionNodeIds.set(element, identifier);
    }
    return identifier;
  };

  const box = (element) => {
    const rect = element.getBoundingClientRect();
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      return null;
    }
    return {
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
    };
  };

  const visible = (element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return Boolean(
      element.isConnected &&
      style.display !== "none" &&
      style.visibility !== "hidden" &&
      rect.width > 0 &&
      rect.height > 0
    );
  };

  const text = (element) => (element.innerText || element.textContent || "").trim();
  const disabled = (element) => Boolean(
    element.disabled ||
    element.matches(":disabled") ||
    element.hasAttribute("disabled") ||
    element.getAttribute("aria-disabled") === "true"
  );

  const describe = (element) => ({
    node_debug_id: nodeId(element),
    tag: element.tagName.toLowerCase(),
    role: element.getAttribute("role"),
    text: text(element),
    visible: visible(element),
    enabled: !disabled(element),
    disabled: disabled(element),
    aria_disabled: element.getAttribute("aria-disabled"),
    bounding_box: box(element),
  });

  const dialogs = Array.from(
    document.querySelectorAll('[role="dialog"], dialog')
  ).filter(visible);

  const buttons = Array.from(
    document.querySelectorAll('button, [role="button"]')
  ).filter(visible);

  const customerMarker = /Jenis\s+Pelanggan|Pelanggan\s+Terdaftar|pilihan\s+jenis\s+pelanggan/i;
  const allRadios = Array.from(
    document.querySelectorAll('input[type="radio"], [role="radio"]')
  );
  const customerRadios = allRadios.filter((radio) => {
    const container = radio.closest('[role="dialog"], section, form');
    return Boolean(container && customerMarker.test(text(container)));
  });

  return {
    dialogs: dialogs.map((dialog) => ({
      ...describe(dialog),
      text: text(dialog),
    })),
    buttons: buttons.map(describe),
    customer_type_radios: customerRadios.map((radio) => {
      const label = radio.closest("label");
      return {
        ...describe(radio),
        checked: Boolean(
          radio.checked || radio.getAttribute("aria-checked") === "true"
        ),
        aria_checked: radio.getAttribute("aria-checked"),
        value: radio.getAttribute("value"),
        name: radio.getAttribute("name"),
        label_text: label ? text(label) : "",
      };
    }),
  };
}
"""

_NODE_ID_SCRIPT = r"""
(element) => {
  const root = window;
  if (!root.__taskbotInteractionNodeIds) {
    root.__taskbotInteractionNodeIds = new WeakMap();
    root.__taskbotInteractionNodeSequence = 0;
  }
  let identifier = root.__taskbotInteractionNodeIds.get(element);
  if (!identifier) {
    root.__taskbotInteractionNodeSequence += 1;
    identifier = `node-${root.__taskbotInteractionNodeSequence}`;
    root.__taskbotInteractionNodeIds.set(element, identifier);
  }
  return {attached: element.isConnected, node_debug_id: identifier};
}
"""

_ELEMENT_FROM_POINT_SCRIPT = r"""
(element, point) => {
  const top = document.elementFromPoint(point.x, point.y);
  if (!top) {
    return {
      center: point,
      target_or_descendant_at_center: false,
      top_element: null,
    };
  }
  return {
    center: point,
    target_or_descendant_at_center: top === element || element.contains(top),
    top_element: {
      tag: top.tagName.toLowerCase(),
      id: top.id || null,
      role: top.getAttribute("role"),
      class_name: typeof top.className === "string" ? top.className : "",
      text: (top.innerText || top.textContent || "").trim(),
    },
  };
}
"""


def _parse_env_flag(
    name: str,
    environ: Mapping[str, str] | None = None,
) -> bool:
    source = os.environ if environ is None else environ
    value = source.get(name, "").strip().casefold()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be one of: 1, 0, true, false, yes, no, on, or off.")


def interaction_debug_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return _parse_env_flag(_DEBUG_ENV, environ)


def interaction_pause_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return _parse_env_flag(_PAUSE_ENV, environ)


def sanitize_diagnostic_text(value: object) -> str:
    """Scrub diagnostic text even when normal NIK masking is disabled."""
    text = _DIAGNOSTIC_NIK_PATTERN.sub("<redacted-nik>", str(value))
    text = _DIAGNOSTIC_LONG_NUMBER_PATTERN.sub("<redacted-number>", text)
    text = sanitize_text(text)
    text = _DIAGNOSTIC_SECRET_PATTERN.sub(r"\1=<redacted>", text)
    text = _DIAGNOSTIC_JWT_PATTERN.sub("<redacted-token>", text)
    return text


def sanitize_diagnostic_message(value: object) -> str:
    """Scrub free-form errors, including query strings embedded in URLs."""
    text = str(value)
    text = _URL_IN_TEXT_PATTERN.sub(
        lambda match: sanitize_diagnostic_url(match.group(0)),
        text,
    )
    return sanitize_diagnostic_text(text)


def sanitize_diagnostic_url(value: object) -> str:
    """Keep an endpoint useful while removing credentials, query values, and fragments."""
    raw_url = str(value)
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return sanitize_diagnostic_text(raw_url.split("?", 1)[0].split("#", 1)[0])

    if parsed.scheme.casefold() not in {"http", "https"}:
        scheme = sanitize_diagnostic_text(parsed.scheme or "unknown")
        return f"{scheme}:<redacted>"

    try:
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        hostname = "<invalid-host>"
        port = None
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if port is not None:
        netloc = f"{netloc}:{port}"

    path = _DIAGNOSTIC_SECRET_PATH_PATTERN.sub(r"\1<redacted>", parsed.path)
    path = _DIAGNOSTIC_OPAQUE_PATH_PATTERN.sub("<redacted-segment>", path)
    path = sanitize_diagnostic_text(path)
    query = "<redacted>" if parsed.query else ""
    return urlunsplit((parsed.scheme, netloc, path, query, ""))


def attach_page_diagnostics(page: Page, diagnostics: InteractionDiagnostics) -> None:
    setattr(page, _PAGE_DIAGNOSTICS_ATTRIBUTE, diagnostics)


def get_page_diagnostics(page: Page | object) -> InteractionDiagnostics | None:
    return getattr(page, _PAGE_DIAGNOSTICS_ATTRIBUTE, None)


def detach_page_diagnostics(
    page: Page | object,
    diagnostics: InteractionDiagnostics,
) -> None:
    if get_page_diagnostics(page) is diagnostics:
        try:
            delattr(page, _PAGE_DIAGNOSTICS_ATTRIBUTE)
        except AttributeError:
            pass


class InteractionDiagnostics:
    """Collect temporary, secret-safe evidence for selected UI interactions."""

    def __init__(
        self,
        *,
        page: Page,
        context: BrowserContext,
        run_dir: str | Path,
        operator_id: str,
        pause_enabled: bool = False,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.page = page
        self.context = context
        sanitized_operator = sanitize_diagnostic_text(operator_id)
        self.operator_id = (
            _SAFE_LABEL_PATTERN.sub("_", sanitized_operator).strip("._")
            or "unknown_operator"
        )[:64]
        self.pause_enabled = pause_enabled
        self.trace_path = (
            Path(run_dir) / "artifacts" / "traces" / self.operator_id / "trace.zip"
        )
        self.screenshot_dir = (
            Path(run_dir)
            / "artifacts"
            / "screenshots"
            / self.operator_id
            / "interaction_debug"
        )
        self._monotonic = monotonic
        self._started_at = monotonic()
        self._trace_started = False
        self._network_active = False
        self._screenshot_sequence = 0
        self._request_sequence = 0
        self._requests: dict[int, dict[str, Any]] = {}
        self._phase = "post_login"

    def start(self) -> None:
        attach_page_diagnostics(self.page, self)
        try:
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self.context.tracing.start(
                screenshots=True,
                snapshots=True,
                sources=True,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostics must not alter the workflow.
            self._log_failure("trace_start", exc)
        else:
            self._trace_started = True
            logger.bind(
                event="playwright.interaction.trace.started",
                operator_id=self.operator_id,
                artifact_path=str(self.trace_path),
            ).info("Playwright interaction trace started")

        try:
            self.context.on("request", self._on_request)
            self.context.on("response", self._on_response)
            self.context.on("requestfinished", self._on_request_finished)
            self.context.on("requestfailed", self._on_request_failed)
        except Exception as exc:  # noqa: BLE001 - diagnostics must not alter the workflow.
            self._log_failure("network_listener_start", exc)
        else:
            self._network_active = True
            logger.bind(
                event="playwright.interaction.network.started",
                operator_id=self.operator_id,
                resource_types=sorted(_NETWORK_RESOURCE_TYPES),
            ).info("Playwright interaction network diagnostics started")

    def stop(self, *, context_manager_failed: bool) -> None:
        self._network_active = False
        try:
            try:
                self._log_pending_requests()
            except Exception:  # noqa: BLE001 - trace finalization has priority.
                self._requests.clear()

            if self._trace_started:
                try:
                    self.context.tracing.stop(path=str(self.trace_path))
                except Exception as exc:  # noqa: BLE001 - do not mask the workflow.
                    try:
                        self._log_failure("trace_stop", exc)
                    except Exception:  # noqa: BLE001, S110 - cleanup has priority.
                        pass
                else:
                    try:
                        logger.bind(
                            event="playwright.interaction.trace.saved",
                            operator_id=self.operator_id,
                            artifact_path=str(self.trace_path),
                            context_manager_failed=context_manager_failed,
                        ).info("Playwright interaction trace saved")
                    except Exception:  # noqa: BLE001, S110 - cleanup has priority.
                        pass
        finally:
            self._trace_started = False
            detach_page_diagnostics(self.page, self)

    def mark_phase(self, label: str) -> None:
        self._phase = sanitize_diagnostic_text(label)

    def debug_interaction_state(self, label: str) -> None:
        self.mark_phase(label)
        try:
            raw_state = self.page.evaluate(_DOM_STATE_SCRIPT)
            state = self._scrub_value(raw_state)
            dialogs = list(state.get("dialogs", []))
            buttons = list(state.get("buttons", []))
            radios = list(state.get("customer_type_radios", []))
            safe_url = sanitize_diagnostic_url(self.page.url)

            logger.bind(
                event="playwright.interaction.state",
                operator_id=self.operator_id,
                label=self._phase,
                url=safe_url,
                visible_dialog_count=len(dialogs),
                visible_button_count=len(buttons),
                customer_type_radio_count=len(radios),
            ).info("Playwright interaction state captured")

            for index, dialog in enumerate(dialogs):
                logger.bind(
                    event="playwright.interaction.dialog",
                    operator_id=self.operator_id,
                    label=self._phase,
                    index=index,
                    **dialog,
                ).info("Visible dialog captured")

            for index, button in enumerate(buttons):
                logger.bind(
                    event="playwright.interaction.button",
                    operator_id=self.operator_id,
                    label=self._phase,
                    index=index,
                    **button,
                ).info("Visible button captured")

            for index, radio in enumerate(radios):
                logger.bind(
                    event="playwright.interaction.radio",
                    operator_id=self.operator_id,
                    label=self._phase,
                    index=index,
                    **radio,
                ).info("Customer-type radio captured")
        except Exception as exc:  # noqa: BLE001 - diagnostics must not alter the workflow.
            self._log_failure("state_capture", exc, label=self._phase)

    def debug_target_locator(
        self,
        label: str,
        target_name: str,
        locator: Locator,
    ) -> None:
        self.mark_phase(label)
        safe_target_name = sanitize_diagnostic_text(target_name)
        try:
            locator_count = locator.count()
        except Exception as exc:  # noqa: BLE001 - diagnostics must not alter the workflow.
            self._log_failure(
                "target_count",
                exc,
                label=self._phase,
                target_name=safe_target_name,
            )
            return

        logger.bind(
            event="playwright.interaction.target",
            operator_id=self.operator_id,
            label=self._phase,
            target_name=safe_target_name,
            locator_count=locator_count,
        ).info("Target locator captured")

        for index in range(locator_count):
            record = self._read_target_match(locator.nth(index), index=index)
            logger.bind(
                event="playwright.interaction.target_match",
                operator_id=self.operator_id,
                label=self._phase,
                target_name=safe_target_name,
                **record,
            ).info("Target locator match captured")

    def screenshot(self, label: str) -> Path | None:
        self.mark_phase(label)
        self._screenshot_sequence += 1
        safe_label = _SAFE_LABEL_PATTERN.sub("_", self._phase).strip("._")
        safe_label = (safe_label or "interaction")[:80]
        output_path = self.screenshot_dir / (
            f"{self._screenshot_sequence:04d}_{safe_label}.png"
        )
        try:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            sensitive_fields = self.page.locator(
                "input:not([type='radio']):not([type='checkbox']), textarea"
            )
            self.page.screenshot(
                path=str(output_path),
                full_page=True,
                mask=[sensitive_fields],
                mask_color="#000000",
            )
        except Exception as exc:  # noqa: BLE001 - diagnostics must not alter the workflow.
            self._log_failure(
                "screenshot",
                exc,
                label=self._phase,
                artifact_path=str(output_path),
            )
            return None

        logger.bind(
            event="playwright.interaction.screenshot.saved",
            operator_id=self.operator_id,
            label=self._phase,
            artifact_path=str(output_path),
        ).info("Playwright interaction screenshot saved")
        return output_path

    def poll_state_changes(
        self,
        label: str,
        probes: Mapping[str, Callable[[], bool]],
        *,
        duration_ms: int = 20_000,
        interval_ms: int = 250,
        on_change: Callable[[str, bool | None, bool, int], None] | None = None,
    ) -> None:
        if duration_ms < 20_000:
            raise ValueError(
                "Interaction diagnostic polling must run for at least 20000ms."
            )
        if interval_ms <= 0 or interval_ms > 1_000:
            raise ValueError(
                "Interaction diagnostic polling interval must be 1..1000ms."
            )

        self.mark_phase(label)
        poll_label = self._phase
        previous: dict[str, bool] = {}
        probe_errors: dict[str, str] = {}
        elapsed_ms = 0
        logger.bind(
            event="playwright.interaction.poll.started",
            operator_id=self.operator_id,
            label=poll_label,
            duration_ms=duration_ms,
            interval_ms=interval_ms,
        ).info("Playwright interaction state polling started")

        while True:
            for state_name, probe in probes.items():
                try:
                    current = bool(probe())
                except Exception as exc:  # noqa: BLE001 - one probe must not stop evidence.
                    error_signature = f"{type(exc).__name__}: {exc}"
                    if probe_errors.get(state_name) != error_signature:
                        probe_errors[state_name] = error_signature
                        self._log_failure(
                            "state_probe",
                            exc,
                            label=poll_label,
                            state_name=state_name,
                        )
                    continue
                probe_errors.pop(state_name, None)

                prior = previous.get(state_name)
                if prior is current:
                    continue
                previous[state_name] = current
                logger.bind(
                    event="playwright.interaction.state_change",
                    operator_id=self.operator_id,
                    label=poll_label,
                    state_name=state_name,
                    previous=prior,
                    current=current,
                    elapsed_ms=elapsed_ms,
                ).info(f"{state_name}: {prior} -> {current}")
                if on_change is not None:
                    try:
                        on_change(state_name, prior, current, elapsed_ms)
                    except Exception as exc:  # noqa: BLE001 - callback is diagnostic only.
                        self._log_failure(
                            "state_change_callback",
                            exc,
                            label=poll_label,
                            state_name=state_name,
                        )
                    finally:
                        self._phase = poll_label

            if elapsed_ms >= duration_ms:
                break
            wait_ms = min(interval_ms, duration_ms - elapsed_ms)
            try:
                self.page.wait_for_timeout(wait_ms)
            except Exception as exc:  # noqa: BLE001 - diagnostics must not alter the workflow.
                self._log_failure("poll_wait", exc, label=poll_label)
                break
            elapsed_ms += wait_ms

        logger.bind(
            event="playwright.interaction.poll.finished",
            operator_id=self.operator_id,
            label=poll_label,
            observed_ms=elapsed_ms,
            final_states=previous,
        ).info("Playwright interaction state polling finished")

    def pause(self, label: str) -> None:
        if not self.pause_enabled:
            return
        self.mark_phase(label)
        logger.bind(
            event="playwright.interaction.pause",
            operator_id=self.operator_id,
            label=self._phase,
        ).info("Playwright interaction pause reached")
        try:
            self.page.pause()
        except Exception as exc:  # noqa: BLE001 - diagnostics must not alter the workflow.
            self._log_failure("pause", exc, label=self._phase)

    def _read_target_match(self, locator: Locator, *, index: int) -> dict[str, Any]:
        record: dict[str, Any] = {
            "index": index,
            "attached": False,
            "visible": False,
            "enabled": False,
            "text": "",
            "aria_disabled": None,
            "bounding_box": None,
            "element_from_point": None,
            "errors": [],
        }

        def capture(field: str, callback: Callable[[], Any], default: Any) -> Any:
            try:
                return callback()
            except Exception as exc:  # noqa: BLE001 - DOM can change between probes.
                record["errors"].append(
                    f"{field}: {sanitize_diagnostic_text(type(exc).__name__)}"
                )
                return default

        identity = capture(
            "attached",
            lambda: locator.evaluate(
                _NODE_ID_SCRIPT,
                timeout=_LOCATOR_PROBE_TIMEOUT_MS,
            ),
            {},
        )
        record.update(identity)
        record["visible"] = capture("visible", locator.is_visible, False)
        record["enabled"] = capture(
            "enabled",
            lambda: locator.is_enabled(timeout=_LOCATOR_PROBE_TIMEOUT_MS),
            False,
        )
        record["text"] = sanitize_diagnostic_text(
            capture(
                "text",
                lambda: locator.inner_text(timeout=_LOCATOR_PROBE_TIMEOUT_MS),
                "",
            )
        )
        record["aria_disabled"] = (
            sanitize_diagnostic_text(
                capture(
                    "aria_disabled",
                    lambda: locator.get_attribute(
                        "aria-disabled",
                        timeout=_LOCATOR_PROBE_TIMEOUT_MS,
                    ),
                    "",
                )
                or ""
            )
            or None
        )
        bounding_box = capture(
            "bounding_box",
            lambda: locator.bounding_box(timeout=_LOCATOR_PROBE_TIMEOUT_MS),
            None,
        )
        record["bounding_box"] = bounding_box
        if bounding_box is not None:
            center = {
                "x": bounding_box["x"] + bounding_box["width"] / 2,
                "y": bounding_box["y"] + bounding_box["height"] / 2,
            }
            hit_test = capture(
                "element_from_point",
                lambda: locator.evaluate(
                    _ELEMENT_FROM_POINT_SCRIPT,
                    center,
                    timeout=_LOCATOR_PROBE_TIMEOUT_MS,
                ),
                None,
            )
            record["element_from_point"] = self._scrub_value(hit_test)

        return record

    def _on_request(self, request: Request) -> None:
        self._network_callback(
            "request",
            request,
            lambda: self._record_request_event(request),
        )

    def _on_response(self, response: Response) -> None:
        if not self._network_active:
            return
        try:
            request = response.request
        except Exception as exc:  # noqa: BLE001 - event callbacks must never escape.
            self._log_failure(
                "network_callback",
                exc,
                network_event="response",
            )
            return

        def record() -> None:
            request_record = self._ensure_request_record(request)
            request_record["status"] = response.status
            logger.bind(
                event="playwright.interaction.network.response",
                operator_id=self.operator_id,
                phase=request_record["origin_phase"],
                observed_phase=self._phase,
                request_id=request_record["request_id"],
                method=request_record["method"],
                url=request_record["url"],
                resource_type=request_record["resource_type"],
                status=response.status,
                response_elapsed_ms=self._elapsed_since(request_record["started_at"]),
            ).info("Playwright interaction response observed")

        self._network_callback("response", request, record)

    def _on_request_finished(self, request: Request) -> None:
        def record() -> None:
            request_record = self._ensure_request_record(request)
            timing = {
                key: value
                for key, value in dict(request.timing).items()
                if isinstance(value, int | float)
            }
            logger.bind(
                event="playwright.interaction.network.finished",
                operator_id=self.operator_id,
                phase=request_record["origin_phase"],
                observed_phase=self._phase,
                request_id=request_record["request_id"],
                method=request_record["method"],
                url=request_record["url"],
                resource_type=request_record["resource_type"],
                status=request_record.get("status"),
                total_elapsed_ms=self._elapsed_since(request_record["started_at"]),
                playwright_timing=timing,
            ).info("Playwright interaction request finished")
            self._requests.pop(id(request), None)

        self._network_callback("requestfinished", request, record)

    def _on_request_failed(self, request: Request) -> None:
        def record() -> None:
            request_record = self._ensure_request_record(request)
            logger.bind(
                event="playwright.interaction.network.failed",
                operator_id=self.operator_id,
                phase=request_record["origin_phase"],
                observed_phase=self._phase,
                request_id=request_record["request_id"],
                method=request_record["method"],
                url=request_record["url"],
                resource_type=request_record["resource_type"],
                total_elapsed_ms=self._elapsed_since(request_record["started_at"]),
                failure=sanitize_diagnostic_text(request.failure or "unknown"),
            ).info("Playwright interaction request failed")
            self._requests.pop(id(request), None)

        self._network_callback("requestfailed", request, record)

    def _network_callback(
        self,
        event_name: str,
        request: Request,
        callback: Callable[[], None],
    ) -> None:
        if not self._network_active:
            return
        try:
            if request.resource_type not in _NETWORK_RESOURCE_TYPES:
                return
            callback()
        except Exception as exc:  # noqa: BLE001 - event callbacks must never affect Playwright.
            self._log_failure(
                "network_callback",
                exc,
                network_event=event_name,
            )

    def _ensure_request_record(self, request: Request) -> dict[str, Any]:
        key = id(request)
        existing = self._requests.get(key)
        if existing is not None:
            return existing
        self._request_sequence += 1
        record = {
            "request_id": self._request_sequence,
            "started_at": self._monotonic(),
            "method": sanitize_diagnostic_text(request.method),
            "url": sanitize_diagnostic_url(request.url),
            "resource_type": sanitize_diagnostic_text(request.resource_type),
            "origin_phase": self._phase,
        }
        self._requests[key] = record
        return record

    def _record_request_event(self, request: Request) -> None:
        request_record = self._ensure_request_record(request)
        logger.bind(
            event="playwright.interaction.network.request",
            operator_id=self.operator_id,
            phase=request_record["origin_phase"],
            request_id=request_record["request_id"],
            method=request_record["method"],
            url=request_record["url"],
            resource_type=request_record["resource_type"],
            session_elapsed_ms=self._elapsed_since(self._started_at),
        ).info("Playwright interaction request observed")

    def _elapsed_since(self, started_at: float) -> int:
        return max(0, round((self._monotonic() - started_at) * 1000))

    def _log_pending_requests(self) -> None:
        for request_record in list(self._requests.values()):
            logger.bind(
                event="playwright.interaction.network.pending",
                operator_id=self.operator_id,
                phase=request_record["origin_phase"],
                observed_phase=self._phase,
                request_id=request_record["request_id"],
                method=request_record["method"],
                url=request_record["url"],
                resource_type=request_record["resource_type"],
                status=request_record.get("status"),
                total_elapsed_ms=self._elapsed_since(request_record["started_at"]),
            ).info("Playwright interaction request was still pending at cleanup")
        self._requests.clear()

    @classmethod
    def _scrub_value(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): cls._scrub_value(item) for key, item in value.items()}
        if isinstance(value, list | tuple | set):
            return [cls._scrub_value(item) for item in value]
        if isinstance(value, str):
            return sanitize_diagnostic_text(value)
        return value

    def _log_failure(self, operation: str, exc: Exception, **fields: Any) -> None:
        logger.bind(
            event="playwright.interaction.diagnostic_failed",
            operator_id=self.operator_id,
            operation=operation,
            error_type=type(exc).__name__,
            error=sanitize_diagnostic_message(exc),
            **self._scrub_value(fields),
        ).warning("Playwright interaction diagnostic failed")


__all__ = [
    "InteractionDiagnostics",
    "attach_page_diagnostics",
    "detach_page_diagnostics",
    "get_page_diagnostics",
    "interaction_debug_enabled",
    "interaction_pause_enabled",
    "sanitize_diagnostic_message",
    "sanitize_diagnostic_text",
    "sanitize_diagnostic_url",
]
