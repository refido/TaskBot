"""Canonical local parser for Indonesian NIK customer-update fields."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent / "nik_region_mapping.json"
_NIK_PATTERN = re.compile(r"\d{16}")


class NIKValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RegionMapping:
    provinces: Mapping[str, str]
    regencies: Mapping[str, str]
    districts: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class NIKResult:
    original_nik: str
    provinsi: str
    kota_kabupaten: str
    kecamatan: str
    birth_date: date
    jenis_kelamin: str


def normalise_nik(value: str) -> str:
    if not isinstance(value, str):
        raise NIKValidationError("NIK must be text")
    normalized = re.sub(r"[\s.-]", "", value.strip())
    if _NIK_PATTERN.fullmatch(normalized) is None:
        raise NIKValidationError("NIK must contain exactly 16 ASCII digits")
    return normalized


def _index(records: object, section: str) -> dict[str, str]:
    if not isinstance(records, list):
        raise NIKValidationError(f"Mapping section {section!r} must be a list")
    result: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict):
            raise NIKValidationError(f"Invalid record in mapping section {section!r}")
        code, name = record.get("code"), record.get("name")
        if not isinstance(code, str) or not isinstance(name, str):
            raise NIKValidationError(f"Mapping section {section!r} requires code/name")
        result[code] = name
    return result


@lru_cache(maxsize=4)
def load_region_mapping(path: str | Path = DEFAULT_MAPPING_PATH) -> RegionMapping:
    mapping_path = Path(path)
    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NIKValidationError(f"Cannot load region mapping: {mapping_path}") from exc
    if not isinstance(payload, dict):
        raise NIKValidationError("Region mapping must contain a JSON object")
    return RegionMapping(
        provinces=_index(payload.get("provinces"), "provinces"),
        regencies=_index(payload.get("regencies"), "regencies"),
        districts=_index(payload.get("districts"), "districts"),
    )


def parse_nik(
    value: str,
    mapping: RegionMapping | None = None,
    *,
    reference_date: date | None = None,
) -> NIKResult:
    nik = normalise_nik(value)
    regions = mapping or load_region_mapping()
    province_code = nik[:2]
    regency_code = f"{nik[:2]}.{nik[2:4]}"
    district_code = f"{nik[:2]}.{nik[2:4]}.{nik[4:6]}"
    try:
        province = regions.provinces[province_code]
        regency = regions.regencies[regency_code]
        district = regions.districts[district_code]
    except KeyError as exc:
        raise NIKValidationError(f"Unknown NIK region code: {exc.args[0]}") from exc

    encoded_day = int(nik[6:8])
    if 1 <= encoded_day <= 31:
        day, gender = encoded_day, "Laki-laki"
    elif 41 <= encoded_day <= 71:
        day, gender = encoded_day - 40, "Perempuan"
    else:
        raise NIKValidationError("Invalid NIK birth-day code")
    month, suffix = int(nik[8:10]), int(nik[10:12])
    today = reference_date or datetime.now(UTC).astimezone().date()
    year = 2000 + suffix
    try:
        birth_date = date(year, month, day)
        if birth_date > today:
            birth_date = date(year - 100, month, day)
    except ValueError as exc:
        raise NIKValidationError("Invalid birth date encoded in NIK") from exc

    return NIKResult(nik, province, regency, district, birth_date, gender)
