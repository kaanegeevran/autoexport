"""Tests for config loading and CLI, including new features."""

import pytest
from pathlib import Path
from autoexport.config import Config, ExportMode, ImportStyle, load_config
from autoexport.cli import main


# ═══════════════════════════════════════════════════════════════════════
# CONFIG DEFAULTS
# ═══════════════════════════════════════════════════════════════════════


class TestConfigDefaults:
    def test_default_values(self):
        c = Config()
        assert c.watch == ["."]
        assert c.mode == ExportMode.ALL
        assert c.import_style == ImportStyle.RELATIVE
        assert c.export_constants is True
        assert c.export_variables is False
        assert c.flatten is False
        assert c.lazy is False
        assert c.use_black is False
        assert c.recursive is True
        assert c.respect_existing_all is True

    def test_watch_paths(self):
        c = Config(watch=["src/app", "src/lib"])
        assert c.watch_paths == [Path("src/app"), Path("src/lib")]


# ═══════════════════════════════════════════════════════════════════════
# CONFIG FROM TOML
# ═══════════════════════════════════════════════════════════════════════


class TestConfigFromToml:
    def test_load_autoexport_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["src/app", "src/lib"]
mode = "decorated"
export_constants = false
recursive = false
""")
        config = load_config()
        assert config.watch == ["src/app", "src/lib"]
        assert config.mode == ExportMode.DECORATED
        assert config.export_constants is False
        assert config.recursive is False

    def test_load_pyproject_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "pyproject.toml").write_text("""
[tool.autoexport]
watch = ["app"]
mode = "public"
""")
        config = load_config()
        assert config.watch == ["app"]
        assert config.mode == ExportMode.PUBLIC

    def test_autoexport_toml_takes_priority(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["from_autoexport"]
""")
        (tmp_path / "pyproject.toml").write_text("""
[tool.autoexport]
watch = ["from_pyproject"]
""")
        config = load_config()
        assert config.watch == ["from_autoexport"]

    def test_no_config_file_uses_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.watch == ["."]

    def test_explicit_path(self, tmp_path):
        p = tmp_path / "custom.toml"
        p.write_text("""
[autoexport]
watch = ["custom_dir"]
export_variables = true
""")
        config = load_config(config_path=p)
        assert config.watch == ["custom_dir"]
        assert config.export_variables is True

    def test_load_new_options(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["app"]
import_style = "absolute"
flatten = true
lazy = true
use_black = true
""")
        config = load_config()
        assert config.import_style == ImportStyle.ABSOLUTE
        assert config.flatten is True
        assert config.lazy is True
        assert config.use_black is True

    def test_load_partial_config(self, tmp_path, monkeypatch):
        """Unspecified keys should keep defaults."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
flatten = true
""")
        config = load_config()
        assert config.flatten is True
        assert config.lazy is False  # default
        assert config.mode == ExportMode.ALL  # default
        assert config.import_style == ImportStyle.RELATIVE  # default


# ═══════════════════════════════════════════════════════════════════════
# CLI COMMANDS
# ═══════════════════════════════════════════════════════════════════════


class TestCLI:
    def test_init_creates_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ret = main(["init", "--watch", "src/app", "src/lib"])
        assert ret == 0
        assert (tmp_path / "autoexport.toml").exists()
        content = (tmp_path / "autoexport.toml").read_text()
        assert "src/app" in content
        assert "src/lib" in content

    def test_init_contains_new_options(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        main(["init"])
        content = (tmp_path / "autoexport.toml").read_text()
        assert "flatten" in content
        assert "lazy" in content
        assert "use_black" in content
        assert "import_style" in content

    def test_init_fails_if_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "autoexport.toml").write_text("[autoexport]\n")
        ret = main(["init"])
        assert ret == 1

    def test_generate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["models"]
""")
        ret = main(["generate"])
        assert ret == 0
        assert (models / "__init__.py").exists()
        content = (models / "__init__.py").read_text()
        assert "from .user import User" in content

    def test_generate_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["models"]
""")
        ret = main(["generate", "--dry-run"])
        assert ret == 0
        assert not (models / "__init__.py").exists()

    def test_generate_diff(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["models"]
""")
        ret = main(["generate", "--diff"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "User" in captured.out
        # File should NOT be written in diff mode
        assert not (models / "__init__.py").exists()

    def test_clean(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["models"]
""")
        # Generate first
        main(["generate"])
        assert (models / "__init__.py").exists()

        # Clean
        ret = main(["clean"])
        assert ret == 0
        assert not (models / "__init__.py").exists()

    def test_clean_preserves_handwritten(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        models = tmp_path / "models"
        models.mkdir()
        (models / "__init__.py").write_text("# Hand-written\nfrom .user import User\n")
        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["models"]
""")
        ret = main(["clean"])
        assert ret == 0
        assert (models / "__init__.py").exists()  # NOT removed

    def test_no_command_shows_help(self, capsys):
        ret = main([])
        assert ret == 0


# ═══════════════════════════════════════════════════════════════════════
# END-TO-END
# ═══════════════════════════════════════════════════════════════════════


class TestEndToEnd:
    def test_full_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        # Create project
        (tmp_path / "app" / "models").mkdir(parents=True)
        (tmp_path / "app" / "services").mkdir(parents=True)
        (tmp_path / "app" / "controllers").mkdir(parents=True)

        (tmp_path / "app" / "models" / "user.py").write_text(
            "from dataclasses import dataclass\n\n@dataclass\nclass User:\n    name: str\n    email: str\n"
        )
        (tmp_path / "app" / "models" / "post.py").write_text(
            "class Post:\n    def __init__(self, title: str):\n        self.title = title\n"
        )
        (tmp_path / "app" / "services" / "auth.py").write_text(
            "class AuthService:\n    def login(self, name: str): pass\n"
        )
        (tmp_path / "app" / "services" / "email.py").write_text(
            "class EmailService:\n    def send(self, to: str, body: str): pass\n\nSMTP_HOST = 'localhost'\nSMTP_PORT = 587\n"
        )
        (tmp_path / "app" / "controllers" / "api.py").write_text(
            "class APIController: pass\n"
        )

        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["app"]
mode = "all"
export_constants = true
recursive = true
""")

        ret = main(["generate", "--verbose"])
        assert ret == 0

        # Verify app/__init__.py
        app_init = (tmp_path / "app" / "__init__.py").read_text()
        assert "from . import models" in app_init
        assert "from . import services" in app_init
        assert "from . import controllers" in app_init

        # Verify models
        models_init = (tmp_path / "app" / "models" / "__init__.py").read_text()
        assert "from .post import Post" in models_init
        assert "from .user import User" in models_init

        # Verify services
        services_init = (tmp_path / "app" / "services" / "__init__.py").read_text()
        assert "from .auth import AuthService" in services_init
        assert "from .email import EmailService" in services_init
        assert "from .email import SMTP_HOST" in services_init
        assert "from .email import SMTP_PORT" in services_init

        # Verify controllers
        ctrl_init = (tmp_path / "app" / "controllers" / "__init__.py").read_text()
        assert "from .api import APIController" in ctrl_init

    def test_full_project_with_flatten(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        (tmp_path / "app" / "models").mkdir(parents=True)
        (tmp_path / "app" / "services").mkdir(parents=True)

        (tmp_path / "app" / "models" / "user.py").write_text("class User: pass\n")
        (tmp_path / "app" / "models" / "post.py").write_text("class Post: pass\n")
        (tmp_path / "app" / "services" / "auth.py").write_text("class AuthService: pass\n")

        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["app"]
flatten = true
recursive = true
""")

        ret = main(["generate"])
        assert ret == 0

        app_init = (tmp_path / "app" / "__init__.py").read_text()
        # Flattened exports
        assert "User" in app_init
        assert "Post" in app_init
        assert "AuthService" in app_init
        # Subpackages still accessible
        assert "models" in app_init
        assert "services" in app_init

    def test_full_project_with_lazy(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        (tmp_path / "models").mkdir()
        (tmp_path / "models" / "user.py").write_text("class User: pass\n")
        (tmp_path / "models" / "post.py").write_text("class Post: pass\n")

        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["models"]
lazy = true
""")

        ret = main(["generate"])
        assert ret == 0

        content = (tmp_path / "models" / "__init__.py").read_text()
        assert "def __getattr__" in content
        assert "def __dir__" in content
        assert "_LAZY_IMPORTS" in content

    def test_regeneration_after_change(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        models = tmp_path / "models"
        models.mkdir()
        (models / "user.py").write_text("class User: pass")

        (tmp_path / "autoexport.toml").write_text("""
[autoexport]
watch = ["models"]
""")

        # Initial generation
        main(["generate"])
        init_v1 = (models / "__init__.py").read_text()
        assert "User" in init_v1
        assert "Post" not in init_v1

        # Add a new file
        (models / "post.py").write_text("class Post: pass")

        # Regenerate
        main(["generate"])
        init_v2 = (models / "__init__.py").read_text()
        assert "User" in init_v2
        assert "Post" in init_v2
