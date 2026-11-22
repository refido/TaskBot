from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from dotenv.main import DotEnv

DOTENV_PATH = Path(__file__).resolve().parents[3] / ".env"
_NIK_KEY = re.compile(r"NIK(?:_\d+)?", re.IGNORECASE)
_ENV_VALUE_LIMIT = 32_767


def load_environment(
    environ: Mapping[str, str] | None = None,
    *,
    load_env_file: bool = True,
    dotenv_path: Path | None = None,
) -> Mapping[str, str]:
    """Read full values in memory and export only small, non-NIK settings.

    Existing process variables take precedence, as with load_dotenv's default.
    Explicit mappings and load_env_file=False retain their existing semantics.
    """
    values: dict[str, str] = {}
    disabled = os.getenv("PYTHON_DOTENV_DISABLED", "").casefold() in {
        "1", "true", "t", "yes", "y"
    }
    if load_env_file and not disabled:
        # The parser behind dotenv_values(), with load_dotenv's environment-first
        # interpolation precedence. dict() never writes to os.environ.
        parsed = DotEnv(
            dotenv_path=DOTENV_PATH if dotenv_path is None else dotenv_path,
            encoding="utf-8",
            override=False,
        ).dict()
        values = {
            key.upper() if os.name == "nt" else key: value
            for key, value in parsed.items()
            if value is not None
        }
        for key, value in values.items():
            # Windows counts UTF-16 code units, including surrogate pairs.
            if (
                _NIK_KEY.fullmatch(key) is None
                and len(value.encode("utf-16-le", errors="surrogatepass")) // 2
                <= _ENV_VALUE_LIMIT
            ):
                os.environ.setdefault(key, value)

    if environ is not None:
        return environ
    return {**values, **os.environ}
