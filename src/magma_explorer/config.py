"""User configuration loaded from ``~/.config/magma-explorer/config.toml``.

The file is auto-created with sensible defaults on first launch. Malformed
files are reported via warnings and the caller falls back to defaults so the
user keeps their broken file to inspect.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from platformdirs import user_config_dir

APP_NAME = "magma-explorer"

VALID_COLUMN_IDS: frozenset[str] = frozenset(
    {
        "hash",
        "size",
        "idempotent",
        "right_cancellative",
        "satisfies_255",
        "submitted_at",
        "submitted_by",
        "comment",
    }
)

VALID_SORT_FIELDS: frozenset[str] = frozenset(
    {
        "canonical_hash",
        "size",
        "idempotent",
        "right_cancellative",
        "satisfies_255",
        "submitted_at",
        "submitted_by",
    }
)

VALID_ORDERS: frozenset[str] = frozenset({"asc", "desc"})


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Column:
    id: str
    label: str
    width: int | None = None


@dataclass(frozen=True, slots=True)
class SortKey:
    field: str
    order: str = "asc"


@dataclass(frozen=True, slots=True)
class Config:
    columns: tuple[Column, ...]
    sort: tuple[SortKey, ...]

    @classmethod
    def defaults(cls) -> Self:
        return cls(
            columns=(
                Column("hash", "Hash", 12),
                Column("size", "Size"),
                Column("idempotent", "I"),
                Column("right_cancellative", "RC"),
                Column("satisfies_255", "255"),
            ),
            sort=(
                SortKey("size", "asc"),
                SortKey("canonical_hash", "asc"),
            ),
        )


DEFAULT_CONFIG_TEXT = """\
# Magma Explorer configuration.
# Auto-created on first launch. Edit and restart.

# Columns shown in the browse list. Order in this file is display order.
# Available ids: hash, size, idempotent, right_cancellative, satisfies_255,
#                submitted_at, submitted_by, comment.
# Omit a column to hide it.

[[columns]]
id = "hash"
label = "Hash"
width = 12

[[columns]]
id = "size"
label = "Size"

[[columns]]
id = "idempotent"
label = "I"

[[columns]]
id = "right_cancellative"
label = "RC"

[[columns]]
id = "satisfies_255"
label = "255"

# Sort key for the browse list. First entry is primary; subsequent entries
# break ties. Valid orders: "asc", "desc".

[[sort]]
field = "size"
order = "asc"

[[sort]]
field = "canonical_hash"
order = "asc"
"""


def default_config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "config.toml"


def load(path: Path | None = None) -> tuple[Config, list[str]]:
    """Load config; create the file with defaults if missing.

    Returns ``(config, warnings)``. On malformed input the config is the
    defaults and a single warning describes what went wrong.
    """
    target = path if path is not None else default_config_path()
    warnings: list[str] = []

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
        return Config.defaults(), warnings

    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        warnings.append(f"could not parse {target}: {exc}; using defaults")
        return Config.defaults(), warnings

    try:
        cfg = _parse(raw)
    except ConfigError as exc:
        warnings.append(f"{target} is malformed: {exc}; using defaults")
        return Config.defaults(), warnings

    return cfg, warnings


def _parse(raw: dict) -> Config:
    columns_raw = raw.get("columns", [])
    if not isinstance(columns_raw, list):
        raise ConfigError("`columns` must be a list of tables")

    columns: list[Column] = []
    seen_ids: set[str] = set()
    for i, c in enumerate(columns_raw):
        if not isinstance(c, dict):
            raise ConfigError(f"columns[{i}] is not a table")
        col_id = c.get("id")
        if not isinstance(col_id, str) or col_id not in VALID_COLUMN_IDS:
            raise ConfigError(f"columns[{i}].id={col_id!r} is not a known column id")
        if col_id in seen_ids:
            raise ConfigError(f"duplicate column id {col_id!r}")
        seen_ids.add(col_id)

        label = c.get("label", col_id)
        if not isinstance(label, str):
            raise ConfigError(f"columns[{i}].label must be a string")

        width = c.get("width")
        if width is not None and not isinstance(width, int):
            raise ConfigError(f"columns[{i}].width must be int or unset")

        columns.append(Column(id=col_id, label=label, width=width))

    if not columns:
        raise ConfigError("at least one column must be configured")

    sort_raw = raw.get("sort", [])
    if not isinstance(sort_raw, list):
        raise ConfigError("`sort` must be a list of tables")

    sort: list[SortKey] = []
    for i, s in enumerate(sort_raw):
        if not isinstance(s, dict):
            raise ConfigError(f"sort[{i}] is not a table")
        field_name = s.get("field")
        if not isinstance(field_name, str) or field_name not in VALID_SORT_FIELDS:
            raise ConfigError(f"sort[{i}].field={field_name!r} is not a valid sort field")
        order = s.get("order", "asc")
        if order not in VALID_ORDERS:
            raise ConfigError(f"sort[{i}].order={order!r} must be 'asc' or 'desc'")
        sort.append(SortKey(field=field_name, order=order))

    if not sort:
        sort = list(Config.defaults().sort)

    return Config(columns=tuple(columns), sort=tuple(sort))
