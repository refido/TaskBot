from src.pipelines.slider.success import SuccessDetector
from src.pipelines.slider.types import SliderConfig


class FakeResult:
    def __init__(self, value):
        self.value = value

    def json_value(self):
        return self.value


class FakePage:
    def __init__(self, signal="root_hidden"):
        self.signal = signal
        self.wait_calls = []

    def wait_for_function(self, expression, *, arg, timeout, polling):
        self.wait_calls.append(
            {
                "arg": arg,
                "timeout": timeout,
                "polling": polling,
            }
        )
        return FakeResult(self.signal)


class FakeRoot:
    def __init__(self, handle="root-handle", hidden_fallback=False):
        self.handle = handle
        self.hidden_fallback = hidden_fallback
        self.hidden_waits = 0

    def element_handle(self, *, timeout):
        if isinstance(self.handle, Exception):
            raise self.handle
        return self.handle

    def wait_for(self, *, state, timeout):
        self.hidden_waits += 1
        if not self.hidden_fallback:
            raise TimeoutError("root still visible")


def test_success_detector_waits_once_for_competing_success_signals():
    detector = SuccessDetector(
        SliderConfig(max_wait_success_ms=3500, success_poll_interval_ms=100)
    )
    page = FakePage(signal="selector")
    root = FakeRoot()

    assert detector.check_success(page, root) is True
    assert len(page.wait_calls) == 1
    assert page.wait_calls[0]["timeout"] == 3500
    assert page.wait_calls[0]["polling"] == 100


def test_success_detector_does_not_treat_root_lookup_error_as_success():
    detector = SuccessDetector(SliderConfig())
    page = FakePage(signal="selector")
    root = FakeRoot(handle=RuntimeError("page closed"), hidden_fallback=False)

    assert detector.check_success(page, root) is False
    assert page.wait_calls == []
    assert root.hidden_waits == 1
