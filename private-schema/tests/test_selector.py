from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest

from selector import available, select


def test_explicit_selection(tmp_path: Path):
    target = tmp_path / "bal_schema_v1.3.0.yaml"
    target.write_text("classes: {}\n")
    assert select(tmp_path, "1.3.0") == target


def test_latest_uses_numeric_order(tmp_path: Path):
    older = tmp_path / "bal_schema_v1.9.0.yaml"
    newer = tmp_path / "bal_schema_v1.10.0.yaml"
    older.touch(); newer.touch()
    assert select(tmp_path, "latest") == newer


def test_malformed_names_are_ignored(tmp_path: Path):
    (tmp_path / "bal_schema_v1.2.yaml").touch()
    (tmp_path / "bal_schema_vx.y.z.yaml").touch()
    assert available(tmp_path) == []


def test_missing_version_fails_clearly(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="2.0.0"):
        select(tmp_path, "2.0.0")


def test_tie_order_is_deterministic(tmp_path: Path):
    (tmp_path / "bal_schema_v1.3.0.yaml").touch()
    (tmp_path / "bal_schema_v1.2.0.yml").touch()
    assert [item[1] for item in available(tmp_path)] == ["1.3.0", "1.2.0"]
