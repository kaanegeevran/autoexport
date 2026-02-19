"""Tests for __init__.py generation, including flatten, lazy, absolute imports, diff, and black."""

import pytest
from pathlib import Path
from autoexport.config import Config, ExportMode, ImportStyle
from autoexport.generator import (
    generate_for_directory,
    generate_all,
    write_results,
    diff_results,
    GENERATED_MARKER,
    _is_autoexport_managed,
)


@pytest.fixture
def project(tmp_path):
    """Create a small project structure for testing."""

    def _make(files: dict[str, str]) -> Path:
        for rel_path, content in files.items():
            p = tmp_path / rel_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        return tmp_path

    return _make


# ═══════════════════════════════════════════════════════════════════════
# BASIC GENERATION (existing tests, adapted)
# ═══════════════════════════════════════════════════════════════════════


class TestGenerateBasic:
    def test_single_file_single_class(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])
        result = generate_for_directory(root / "models", config)

        assert "from .user import User" in result.content
        assert '"User"' in result.content
        assert result.changed is True

    def test_multiple_files(self, project):
        root = project({
            "models/user.py": "class User: pass",
            "models/post.py": "class Post: pass",
            "models/comment.py": "class Comment: pass\ndef count_comments(): pass",
        })
        config = Config(watch=[str(root / "models")])
        result = generate_for_directory(root / "models", config)

        assert "from .user import User" in result.content
        assert "from .post import Post" in result.content
        assert "from .comment import Comment" in result.content
        assert "from .comment import count_comments" in result.content

    def test_constants_exported(self, project):
        root = project({
            "config/settings.py": "DEBUG = True\nMAX_RETRIES = 3\n",
        })
        config = Config(watch=[str(root / "config")], export_constants=True)
        result = generate_for_directory(root / "config", config)

        assert "from .settings import DEBUG" in result.content
        assert "from .settings import MAX_RETRIES" in result.content

    def test_constants_not_exported_when_disabled(self, project):
        root = project({
            "config/settings.py": "DEBUG = True\nclass Config: pass\n",
        })
        config = Config(watch=[str(root / "config")], export_constants=False)
        result = generate_for_directory(root / "config", config)

        assert "DEBUG" not in result.content
        assert "from .settings import Config" in result.content

    def test_variables_not_exported_by_default(self, project):
        root = project({
            "app/stuff.py": 'default_name = "world"\nclass Foo: pass\n',
        })
        config = Config(watch=[str(root / "app")])
        result = generate_for_directory(root / "app", config)

        assert "default_name" not in result.content
        assert "from .stuff import Foo" in result.content

    def test_variables_exported_when_enabled(self, project):
        root = project({
            "app/stuff.py": 'default_name = "world"',
        })
        config = Config(watch=[str(root / "app")], export_variables=True)
        result = generate_for_directory(root / "app", config)

        assert "from .stuff import default_name" in result.content

    def test_private_names_skipped(self, project):
        root = project({
            "models/user.py": "class User: pass\nclass _Internal: pass\ndef _helper(): pass\n",
        })
        config = Config(watch=[str(root / "models")])
        result = generate_for_directory(root / "models", config)

        assert "User" in result.content
        assert "_Internal" not in result.content
        assert "_helper" not in result.content

    def test_private_files_skipped(self, project):
        root = project({
            "models/user.py": "class User: pass",
            "models/_internal.py": "class Secret: pass",
        })
        config = Config(watch=[str(root / "models")])
        result = generate_for_directory(root / "models", config)

        assert "User" in result.content
        assert "Secret" not in result.content

    def test_excluded_files_skipped(self, project):
        root = project({
            "app/main.py": "class App: pass",
            "app/conftest.py": "class Fixture: pass",
        })
        config = Config(
            watch=[str(root / "app")],
            exclude_files=["conftest.py"],
        )
        result = generate_for_directory(root / "app", config)

        assert "App" in result.content
        assert "Fixture" not in result.content


# ═══════════════════════════════════════════════════════════════════════
# EXPORT MODES
# ═══════════════════════════════════════════════════════════════════════


class TestExportModes:
    def test_mode_all(self, project):
        root = project({
            "app/stuff.py": "class Foo: pass\ndef bar(): pass\nMAX = 10\nlowvar = 'x'\n",
        })
        config = Config(
            watch=[str(root / "app")],
            mode=ExportMode.ALL,
            export_constants=True,
            export_variables=False,
        )
        result = generate_for_directory(root / "app", config)

        assert "Foo" in result.content
        assert "bar" in result.content
        assert "MAX" in result.content
        assert "lowvar" not in result.content

    def test_mode_public(self, project):
        root = project({
            "app/stuff.py": "class Foo: pass\ndef bar(): pass\nMAX = 10\n",
        })
        config = Config(
            watch=[str(root / "app")],
            mode=ExportMode.PUBLIC,
        )
        result = generate_for_directory(root / "app", config)

        assert "Foo" in result.content
        assert "bar" in result.content
        assert "MAX" not in result.content

    def test_mode_decorated(self, project):
        root = project({
            "app/stuff.py": (
                "from autoexport import export\n"
                "@export\nclass Foo: pass\n"
                "class Bar: pass\n"
                "@export\ndef baz(): pass\n"
                "def qux(): pass\n"
            ),
        })
        config = Config(
            watch=[str(root / "app")],
            mode=ExportMode.DECORATED,
        )
        result = generate_for_directory(root / "app", config)

        assert "Foo" in result.content
        assert "Bar" not in result.content
        assert "baz" in result.content
        assert "qux" not in result.content


# ═══════════════════════════════════════════════════════════════════════
# RESPECT __all__
# ═══════════════════════════════════════════════════════════════════════


class TestRespectExistingAll:
    def test_file_with_all(self, project):
        root = project({
            "models/user.py": '__all__ = ["User"]\nclass User: pass\nclass Admin: pass\n',
        })
        config = Config(watch=[str(root / "models")], respect_existing_all=True)
        result = generate_for_directory(root / "models", config)

        assert "User" in result.content
        assert "Admin" not in result.content

    def test_file_with_all_ignored(self, project):
        root = project({
            "models/user.py": '__all__ = ["User"]\nclass User: pass\nclass Admin: pass\n',
        })
        config = Config(watch=[str(root / "models")], respect_existing_all=False)
        result = generate_for_directory(root / "models", config)

        assert "User" in result.content
        assert "Admin" in result.content


# ═══════════════════════════════════════════════════════════════════════
# SUBPACKAGES
# ═══════════════════════════════════════════════════════════════════════


class TestSubpackages:
    def test_subpackages_imported(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
            "app/services/auth.py": "class Auth: pass",
            "app/main.py": "class App: pass",
        })
        config = Config(watch=[str(root / "app")], recursive=True)
        result = generate_for_directory(root / "app", config)

        assert "from . import models" in result.content
        assert "from . import services" in result.content
        assert "from .main import App" in result.content

    def test_excluded_dirs_skipped(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
            "app/__pycache__/junk.py": "x = 1",
        })
        config = Config(watch=[str(root / "app")])
        result = generate_for_directory(root / "app", config)

        assert "models" in result.content
        assert "__pycache__" not in result.content


# ═══════════════════════════════════════════════════════════════════════
# FLATTEN / BUBBLE-UP
# ═══════════════════════════════════════════════════════════════════════


class TestFlatten:
    def test_flatten_bubbles_up_child_exports(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
            "app/models/post.py": "class Post: pass",
            "app/services/auth.py": "class AuthService: pass",
        })
        config = Config(watch=[str(root / "app")], recursive=True, flatten=True)
        result = generate_for_directory(root / "app", config)

        # Child exports should appear at parent level
        assert "from .models.user import User" in result.content
        assert "from .models.post import Post" in result.content
        assert "from .services.auth import AuthService" in result.content
        # Subpackage imports should still be there
        assert "from . import models" in result.content
        assert "from . import services" in result.content

    def test_flatten_disabled_does_not_bubble(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "app")], recursive=True, flatten=False)
        result = generate_for_directory(root / "app", config)

        assert "from .models.user import User" not in result.content
        assert "from . import models" in result.content

    def test_flatten_deep_nesting(self, project):
        root = project({
            "app/core/db/models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "app")], recursive=True, flatten=True)
        result = generate_for_directory(root / "app", config)

        # Should bubble all the way up
        assert "User" in result.content

    def test_flatten_includes_in_all(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "app")], recursive=True, flatten=True)
        result = generate_for_directory(root / "app", config)

        assert '"User"' in result.content  # In __all__

    def test_flatten_with_constants(self, project):
        root = project({
            "app/config/settings.py": "DEBUG = True\nPORT = 8080\n",
        })
        config = Config(
            watch=[str(root / "app")],
            recursive=True,
            flatten=True,
            export_constants=True,
        )
        result = generate_for_directory(root / "app", config)

        assert "DEBUG" in result.content
        assert "PORT" in result.content


# ═══════════════════════════════════════════════════════════════════════
# LAZY IMPORTS (PEP 562)
# ═══════════════════════════════════════════════════════════════════════


class TestLazyImports:
    def test_lazy_generates_getattr(self, project):
        root = project({
            "models/user.py": "class User: pass",
            "models/post.py": "class Post: pass",
        })
        config = Config(watch=[str(root / "models")], lazy=True)
        result = generate_for_directory(root / "models", config)

        assert "def __getattr__(name):" in result.content
        assert "def __dir__():" in result.content
        assert "_LAZY_IMPORTS" in result.content
        assert '"User"' in result.content
        assert '"Post"' in result.content

    def test_lazy_does_not_have_direct_imports(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")], lazy=True)
        result = generate_for_directory(root / "models", config)

        # Should NOT have direct import lines
        assert "from .user import User" not in result.content

    def test_lazy_has_subpackages(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
            "app/main.py": "class App: pass",
        })
        config = Config(watch=[str(root / "app")], lazy=True, recursive=True)
        result = generate_for_directory(root / "app", config)

        assert "_SUBPACKAGES" in result.content
        assert '"models"' in result.content

    def test_lazy_has_all(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")], lazy=True)
        result = generate_for_directory(root / "models", config)

        assert "__all__" in result.content
        assert '"User"' in result.content

    def test_lazy_with_flatten(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
        })
        config = Config(
            watch=[str(root / "app")],
            lazy=True,
            flatten=True,
            recursive=True,
        )
        result = generate_for_directory(root / "app", config)

        assert "_LAZY_IMPORTS" in result.content
        assert '"User"' in result.content

    def test_lazy_caches_on_access(self, project):
        """The generated __getattr__ should cache values in globals()."""
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")], lazy=True)
        result = generate_for_directory(root / "models", config)

        assert "globals()[name] = val" in result.content


# ═══════════════════════════════════════════════════════════════════════
# ABSOLUTE IMPORTS
# ═══════════════════════════════════════════════════════════════════════


class TestAbsoluteImports:
    def test_absolute_style(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(
            watch=[str(root / "models")],
            import_style=ImportStyle.ABSOLUTE,
        )
        result = generate_for_directory(root / "models", config, package_name="app.models")

        assert "from app.models.user import User" in result.content

    def test_relative_style_default(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])
        result = generate_for_directory(root / "models", config)

        assert "from .user import User" in result.content

    def test_absolute_subpackages(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
            "app/main.py": "class App: pass",
        })
        config = Config(
            watch=[str(root / "app")],
            import_style=ImportStyle.ABSOLUTE,
            recursive=True,
        )
        result = generate_for_directory(root / "app", config, package_name="myproject.app")

        assert "from myproject.app import models" in result.content
        assert "from myproject.app.main import App" in result.content

    def test_absolute_with_lazy(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(
            watch=[str(root / "models")],
            import_style=ImportStyle.ABSOLUTE,
            lazy=True,
        )
        result = generate_for_directory(root / "models", config, package_name="app.models")

        assert "app.models.user" in result.content


# ═══════════════════════════════════════════════════════════════════════
# DIFF MODE
# ═══════════════════════════════════════════════════════════════════════


class TestDiff:
    def test_diff_new_file(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])
        results = generate_all(config)
        diffs = diff_results(results)

        assert len(diffs) == 1
        path, diff_text = diffs[0]
        assert "User" in diff_text
        assert "+" in diff_text  # Added lines

    def test_diff_unchanged(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])

        # Generate first
        results = generate_all(config)
        write_results(results)

        # Diff again — should be empty
        results2 = generate_all(config)
        diffs = diff_results(results2)
        assert len(diffs) == 0

    def test_diff_shows_changes(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])

        # Generate initial
        results = generate_all(config)
        write_results(results)

        # Add a new file
        (root / "models" / "post.py").write_text("class Post: pass")

        # Diff should show the addition
        results2 = generate_all(config)
        diffs = diff_results(results2)
        assert len(diffs) == 1
        _, diff_text = diffs[0]
        assert "Post" in diff_text


# ═══════════════════════════════════════════════════════════════════════
# BLACK FORMATTING
# ═══════════════════════════════════════════════════════════════════════


class TestBlackFormatting:
    def test_black_flag_doesnt_crash_without_black(self, project):
        """If black is not installed, should fall back gracefully."""
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")], use_black=True)
        result = generate_for_directory(root / "models", config)

        # Should still generate valid content regardless
        assert "User" in result.content
        assert GENERATED_MARKER in result.content


# ═══════════════════════════════════════════════════════════════════════
# RECURSIVE GENERATION
# ═══════════════════════════════════════════════════════════════════════


class TestRecursive:
    def test_recursive_generates_all(self, project):
        root = project({
            "app/models/user.py": "class User: pass",
            "app/models/post.py": "class Post: pass",
            "app/services/auth.py": "class AuthService: pass",
            "app/main.py": "class App: pass",
        })
        config = Config(watch=[str(root / "app")], recursive=True)
        results = generate_all(config)

        dirs = [str(r.directory.relative_to(root)) for r in results]
        assert "app" in dirs
        assert "app/models" in dirs
        assert "app/services" in dirs

        # Check models has correct exports
        models_result = [r for r in results if "models" in str(r.directory)][0]
        assert "from .user import User" in models_result.content
        assert "from .post import Post" in models_result.content


# ═══════════════════════════════════════════════════════════════════════
# WRITE RESULTS
# ═══════════════════════════════════════════════════════════════════════


class TestWriteResults:
    def test_writes_new_init(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])
        results = generate_all(config)
        written = write_results(results)

        assert len(written) == 1
        init_content = (root / "models" / "__init__.py").read_text()
        assert "from .user import User" in init_content
        assert GENERATED_MARKER in init_content

    def test_dry_run_doesnt_write(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])
        results = generate_all(config)
        written = write_results(results, dry_run=True)

        assert len(written) == 1
        assert not (root / "models" / "__init__.py").exists()

    def test_doesnt_overwrite_handwritten_init(self, project):
        root = project({
            "models/user.py": "class User: pass",
            "models/__init__.py": "# Hand-written, don't touch\nfrom .user import User",
        })
        config = Config(watch=[str(root / "models")])
        results = generate_all(config)
        written = write_results(results)

        assert len(written) == 0
        content = (root / "models" / "__init__.py").read_text()
        assert "Hand-written" in content

    def test_overwrites_autoexport_managed_init(self, project):
        root = project({
            "models/user.py": "class User: pass\nclass Post: pass",
            "models/__init__.py": f"# old header\n{GENERATED_MARKER}\nfrom .user import User\n",
        })
        config = Config(watch=[str(root / "models")])
        results = generate_all(config)
        written = write_results(results)

        assert len(written) == 1
        content = (root / "models" / "__init__.py").read_text()
        assert "Post" in content

    def test_no_write_when_unchanged(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])

        # First generation
        results = generate_all(config)
        write_results(results)

        # Second generation — should detect no change
        results2 = generate_all(config)
        written2 = write_results(results2)
        assert len(written2) == 0


# ═══════════════════════════════════════════════════════════════════════
# GENERATED CONTENT FORMAT
# ═══════════════════════════════════════════════════════════════════════


class TestGeneratedContent:
    def test_has_header(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")], header="# MY HEADER")
        result = generate_for_directory(root / "models", config)

        assert result.content.startswith("# MY HEADER")

    def test_has_marker(self, project):
        root = project({
            "models/user.py": "class User: pass",
        })
        config = Config(watch=[str(root / "models")])
        result = generate_for_directory(root / "models", config)

        assert GENERATED_MARKER in result.content

    def test_has_all(self, project):
        root = project({
            "models/user.py": "class User: pass",
            "models/post.py": "class Post: pass",
        })
        config = Config(watch=[str(root / "models")])
        result = generate_for_directory(root / "models", config)

        assert "__all__" in result.content
        assert '"User"' in result.content
        assert '"Post"' in result.content

    def test_empty_dir_generates_minimal_init(self, project):
        root = project({})
        empty_dir = root / "empty"
        empty_dir.mkdir()

        config = Config(watch=[str(empty_dir)])
        result = generate_for_directory(empty_dir, config)

        assert GENERATED_MARKER in result.content
        assert "__all__" not in result.content

    def test_imports_sorted_by_file(self, project):
        root = project({
            "models/zebra.py": "class Zebra: pass",
            "models/alpha.py": "class Alpha: pass",
            "models/middle.py": "class Middle: pass",
        })
        config = Config(watch=[str(root / "models")])
        result = generate_for_directory(root / "models", config)

        lines = result.content.split("\n")
        import_lines = [l for l in lines if l.startswith("from .")]
        assert import_lines[0] == "from .alpha import Alpha"
        assert import_lines[1] == "from .middle import Middle"
        assert import_lines[2] == "from .zebra import Zebra"


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


class TestIsAutoexportManaged:
    def test_managed_file(self, tmp_path):
        p = tmp_path / "__init__.py"
        p.write_text(f"# header\n{GENERATED_MARKER}\nfrom .x import X\n")
        assert _is_autoexport_managed(p) is True

    def test_handwritten_file(self, tmp_path):
        p = tmp_path / "__init__.py"
        p.write_text("# My hand-written init\nfrom .x import X\n")
        assert _is_autoexport_managed(p) is False

    def test_nonexistent_file(self, tmp_path):
        p = tmp_path / "__init__.py"
        assert _is_autoexport_managed(p) is False
