from pathlib import Path

from dotenv import dotenv_values

env_path = Path(__file__).resolve().with_name(".env")
values = dotenv_values(env_path)

items = sorted(
    (
        (key, len(value) if value else 0)
        for key, value in values.items()
    ),
    key=lambda x: x[1],
    reverse=True,
)

for key, length in items:
    print(f"{length:>10,} chars | {key}")