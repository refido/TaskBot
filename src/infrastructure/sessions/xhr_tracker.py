import copy
from typing import Any

from playwright.sync_api import CDPSession


class XHRTracker:
    """Capture XHR/fetch traffic plus request and response bodies via CDP."""

    def __init__(self, cdp_session: CDPSession) -> None:
        self.cdp_session = cdp_session
        self._entries: dict[str, dict[str, Any]] = {}
        self._pending_request_extra: dict[str, list[dict[str, Any]]] = {}
        self._pending_response_extra: dict[str, list[dict[str, Any]]] = {}
        self._sequence = 0

    def enable(self) -> None:
        self.cdp_session.send(
            "Network.enable",
            {
                "maxTotalBufferSize": 100_000_000,
                "maxResourceBufferSize": 10_000_000,
                "maxPostDataSize": 10_000_000,
            },
        )
        self.cdp_session.on("Network.requestWillBeSent", self._on_request_will_be_sent)
        self.cdp_session.on(
            "Network.requestWillBeSentExtraInfo",
            self._on_request_will_be_sent_extra_info,
        )
        self.cdp_session.on("Network.responseReceived", self._on_response_received)
        self.cdp_session.on(
            "Network.responseReceivedExtraInfo",
            self._on_response_received_extra_info,
        )
        self.cdp_session.on("Network.loadingFinished", self._on_loading_finished)
        self.cdp_session.on("Network.loadingFailed", self._on_loading_failed)

    def export(self) -> list[dict[str, Any]]:
        entries = sorted(
            self._entries.values(),
            key=lambda item: item.get("sequence", 0),
        )
        exported: list[dict[str, Any]] = []

        for entry in entries:
            request_event = entry.get("events", {}).get("requestWillBeSent", {})
            response_event = entry.get("events", {}).get("responseReceived", {})
            request = request_event.get("request", {})
            response = response_event.get("response", {})

            exported.append(
                {
                    "request_id": entry.get("request_id"),
                    "sequence": entry.get("sequence"),
                    "resource_type": entry.get("resource_type"),
                    "url": request.get("url") or response.get("url"),
                    "method": request.get("method"),
                    "status": response.get("status"),
                    "status_text": response.get("statusText"),
                    "mime_type": response.get("mimeType"),
                    "events": entry.get("events", {}),
                    "request_extra_info": entry.get("request_extra_info", []),
                    "response_extra_info": entry.get("response_extra_info", []),
                    "request_post_data": entry.get("request_post_data"),
                    "request_post_data_error": entry.get("request_post_data_error"),
                    "response_body": entry.get("response_body"),
                    "response_body_error": entry.get("response_body_error"),
                }
            )

        return exported

    def _is_xhr_or_fetch(self, resource_type: str | None) -> bool:
        return resource_type in {"XHR", "Fetch"}

    def _ensure_entry(self, request_id: str) -> dict[str, Any]:
        entry = self._entries.get(request_id)
        if entry is None:
            self._sequence += 1
            entry = {
                "request_id": request_id,
                "sequence": self._sequence,
                "events": {},
                "request_extra_info": [],
                "response_extra_info": [],
            }
            self._entries[request_id] = entry
        return entry

    def _on_request_will_be_sent(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId", ""))
        resource_type = event.get("type")

        if not request_id or not self._is_xhr_or_fetch(resource_type):
            return

        entry = self._ensure_entry(request_id)
        entry["resource_type"] = resource_type
        entry["events"]["requestWillBeSent"] = copy.deepcopy(event)
        entry["request_extra_info"].extend(
            self._pending_request_extra.pop(request_id, [])
        )
        entry["response_extra_info"].extend(
            self._pending_response_extra.pop(request_id, [])
        )

    def _on_request_will_be_sent_extra_info(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId", ""))
        if not request_id:
            return

        payload = copy.deepcopy(event)
        if request_id in self._entries:
            self._entries[request_id]["request_extra_info"].append(payload)
            return

        self._pending_request_extra.setdefault(request_id, []).append(payload)

    def _on_response_received(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId", ""))
        resource_type = event.get("type")

        if not request_id or not self._is_xhr_or_fetch(resource_type):
            return

        entry = self._ensure_entry(request_id)
        entry["resource_type"] = resource_type
        entry["events"]["responseReceived"] = copy.deepcopy(event)
        entry["request_extra_info"].extend(
            self._pending_request_extra.pop(request_id, [])
        )
        entry["response_extra_info"].extend(
            self._pending_response_extra.pop(request_id, [])
        )

    def _on_response_received_extra_info(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId", ""))
        if not request_id:
            return

        payload = copy.deepcopy(event)
        if request_id in self._entries:
            self._entries[request_id]["response_extra_info"].append(payload)
            return

        self._pending_response_extra.setdefault(request_id, []).append(payload)

    def _on_loading_finished(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId", ""))
        entry = self._entries.get(request_id)
        if not entry:
            return

        entry["events"]["loadingFinished"] = copy.deepcopy(event)

        try:
            entry["response_body"] = self.cdp_session.send(
                "Network.getResponseBody",
                {"requestId": request_id},
            )
        except Exception as exc:
            entry["response_body_error"] = str(exc)

        request_event = entry.get("events", {}).get("requestWillBeSent", {})
        if request_event.get("request", {}).get("hasPostData"):
            try:
                entry["request_post_data"] = self.cdp_session.send(
                    "Network.getRequestPostData",
                    {"requestId": request_id},
                )
            except Exception as exc:
                entry["request_post_data_error"] = str(exc)

    def _on_loading_failed(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId", ""))
        entry = self._entries.get(request_id)
        if not entry:
            return

        entry["events"]["loadingFailed"] = copy.deepcopy(event)
