import json

from src.pipelines.slider.artifacts import MetadataWriter
from src.pipelines.slider.types import CoordinateMapping
from src.privacy import set_nik_masking
from src.web.helpers import Helpers


def _mapping() -> CoordinateMapping:
    return CoordinateMapping(
        slot_left_x_img=10.0,
        puzzle_tile_width=20,
        target_x_screen=100.0,
        target_y_screen=50.0,
        current_x=25.0,
        current_y=50.0,
        distance_px=75.0,
        clamped_target_x=100.0,
        rail_limits=(20.0, 180.0),
    )


def test_slider_metadata_carries_run_operator_and_masked_nik(tmp_path):
    MetadataWriter().write_metadata(
        tmp_path,
        (10, 5, 0.98, 1.0, (20, 10)),
        _mapping(),
        (300, 150),
        run_id="20260820_202115_4821",
        operator_id="operator_02",
        nik="357305****720003",
    )

    payload = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "20260820_202115_4821"
    assert payload["operator_id"] == "operator_02"
    assert payload["nik"] == "357305****720003"


def test_puzzle_filename_obeys_mask_with_windows_safe_placeholder():
    class FakePage:
        def locator(self, selector):
            return selector

    nik = "3573051108720003"
    try:
        set_nik_masking(True)
        helpers = Helpers(FakePage())
        masked = helpers.build_puzzle_output_name(nik, "piece")
        assert masked.startswith("357305xxxx720003_")
        assert "*" not in masked

        set_nik_masking(False)
        helpers = Helpers(FakePage())
        assert helpers.build_puzzle_output_name(nik, "piece").startswith(f"{nik}_")
    finally:
        set_nik_masking(True)
