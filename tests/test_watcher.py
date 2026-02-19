"""Tests for the file watcher (snapshot-based, not live watching)."""

import pytest
from pathlib import Path
from autoexport.config import Config
from autoexport.watcher import _take_snapshot


class TestSnapshot:
    def test_snapshot_captures_py_files(self, tmp_path):
        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")
        (models / "post.py").write_text("class Post: pass")

        config = Config(watch=[str(models)])
        snap = _take_snapshot(config)

        assert len(snap) == 2
        assert any("user.py" in k for k in snap)
        assert any("post.py" in k for k in snap)

    def test_snapshot_ignores_init(self, tmp_path):
        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")
        (models / "__init__.py").write_text("from .user import User")

        config = Config(watch=[str(models)])
        snap = _take_snapshot(config)

        assert len(snap) == 1
        assert not any("__init__" in k for k in snap)

    def test_snapshot_ignores_excluded(self, tmp_path):
        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")
        (models / "conftest.py").write_text("import pytest")

        config = Config(watch=[str(models)], exclude_files=["conftest.py"])
        snap = _take_snapshot(config)

        assert len(snap) == 1

    def test_snapshot_detects_changes(self, tmp_path):
        models = tmp_path / "models"
        models.mkdir()
        user_file = models / "user.py"
        user_file.write_text("class User: pass")

        config = Config(watch=[str(models)])
        snap1 = _take_snapshot(config)

        # Modify file
        user_file.write_text("class User:\n    name: str = ''")
        snap2 = _take_snapshot(config)

        assert snap1 != snap2

    def test_snapshot_detects_new_file(self, tmp_path):
        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")

        config = Config(watch=[str(models)])
        snap1 = _take_snapshot(config)

        (models / "post.py").write_text("class Post: pass")
        snap2 = _take_snapshot(config)

        assert len(snap2) == len(snap1) + 1

    def test_snapshot_detects_deleted_file(self, tmp_path):
        models = tmp_path / "models"
        models.mkdir()
        user_file = models / "user.py"
        user_file.write_text("class User: pass")
        (models / "post.py").write_text("class Post: pass")

        config = Config(watch=[str(models)])
        snap1 = _take_snapshot(config)

        user_file.unlink()
        snap2 = _take_snapshot(config)

        assert len(snap2) == len(snap1) - 1

    def test_snapshot_recursive(self, tmp_path):
        (tmp_path / "app" / "models").mkdir(parents=True)
        (tmp_path / "app" / "services").mkdir(parents=True)
        (tmp_path / "app" / "models" / "user.py").write_text("class User: pass")
        (tmp_path / "app" / "services" / "auth.py").write_text("class Auth: pass")

        config = Config(watch=[str(tmp_path / "app")], recursive=True)
        snap = _take_snapshot(config)

        assert len(snap) == 2
