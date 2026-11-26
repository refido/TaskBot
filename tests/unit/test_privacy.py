import pytest

from src import privacy


@pytest.mark.parametrize("mask", [False, True])
def test_sanitize_text_preserves_redaction_order_and_digit_boundaries(
    monkeypatch, mask
):
    monkeypatch.setattr(privacy, "_private_values", set())
    monkeypatch.setattr(privacy, "_mask_nik", mask)
    privacy.register_private_values("dummy-long-value", "dummy-long")
    digits = "０１２３４５６７８９０１２３４５"
    displayed = "０１２３４５****０１２３４５" if mask else digits

    assert privacy.sanitize_text("dummy-long-value") == "<redacted>"
    assert privacy.sanitize_text(f"({digits})") == f"({displayed})"
    assert privacy.sanitize_text(digits[:-1]) == digits[:-1]
    assert privacy.sanitize_text(digits + "0") == digits + "0"
    assert privacy.sanitize_text("user@example.invalid") == "<redacted-email>"
    assert privacy.sanitize_text("PIN : user@example.invalid") == "PIN=<redacted>"
    assert privacy.sanitize_text("ToKeN=dummy-long-value") == "ToKeN=<redacted>"


def test_sanitize_text_reads_actual_characters_of_a_string_subclass():
    class CustomString(str):
        def __str__(self):
            return self

        def __contains__(self, item):
            return False

    assert (
        privacy.sanitize_text(CustomString("user@example.invalid"))
        == "<redacted-email>"
    )
