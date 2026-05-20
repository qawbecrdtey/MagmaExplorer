import textwrap
from pathlib import Path

import pytest

from magma_explorer.config import Config, ConfigError, _parse, load


def test_default_config_writes_file(tmp_path: Path):
    target = tmp_path / "config.toml"
    cfg, warnings = load(target)
    assert warnings == []
    assert target.exists()
    assert isinstance(cfg, Config)
    assert cfg.columns[0].id == "hash"
    assert cfg.sort[0].field == "size"


def test_load_existing_valid_config(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text(
        textwrap.dedent(
            """
            [[columns]]
            id = "size"
            label = "S"

            [[columns]]
            id = "hash"
            label = "H"
            width = 20

            [[sort]]
            field = "size"
            order = "desc"
            """
        ).strip(),
        encoding="utf-8",
    )

    cfg, warnings = load(target)
    assert warnings == []
    assert [c.id for c in cfg.columns] == ["size", "hash"]
    assert cfg.columns[0].label == "S"
    assert cfg.columns[1].width == 20
    assert cfg.sort[0].field == "size"
    assert cfg.sort[0].order == "desc"


def test_load_malformed_toml_warns_and_falls_back(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text("not [valid toml", encoding="utf-8")
    cfg, warnings = load(target)
    assert len(warnings) == 1
    assert cfg == Config.defaults()


def test_unknown_column_id_warns_and_falls_back(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text(
        textwrap.dedent(
            """
            [[columns]]
            id = "totally_made_up"
            """
        ).strip(),
        encoding="utf-8",
    )
    cfg, warnings = load(target)
    assert len(warnings) == 1
    assert cfg == Config.defaults()


def test_duplicate_column_warns_and_falls_back(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text(
        textwrap.dedent(
            """
            [[columns]]
            id = "size"
            [[columns]]
            id = "size"
            """
        ).strip(),
        encoding="utf-8",
    )
    cfg, warnings = load(target)
    assert len(warnings) == 1


def test_invalid_sort_field_warns_and_falls_back(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text(
        textwrap.dedent(
            """
            [[columns]]
            id = "size"

            [[sort]]
            field = "DROP TABLE magmas"
            """
        ).strip(),
        encoding="utf-8",
    )
    cfg, warnings = load(target)
    assert len(warnings) == 1


def test_invalid_sort_order_warns(tmp_path: Path):
    target = tmp_path / "config.toml"
    target.write_text(
        textwrap.dedent(
            """
            [[columns]]
            id = "size"

            [[sort]]
            field = "size"
            order = "sideways"
            """
        ).strip(),
        encoding="utf-8",
    )
    cfg, warnings = load(target)
    assert len(warnings) == 1


def test_parse_rejects_empty_columns():
    with pytest.raises(ConfigError):
        _parse({"columns": []})


def test_parse_empty_sort_uses_default():
    raw = {"columns": [{"id": "size"}]}
    cfg = _parse(raw)
    assert cfg.sort == Config.defaults().sort
