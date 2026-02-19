"""Tests for the AST parser."""

import pytest
from pathlib import Path
from autoexport.parser import parse_file, SymbolKind


@pytest.fixture
def tmp_py(tmp_path):
    """Helper to create a .py file and return its path."""
    def _make(filename: str, content: str) -> Path:
        p = tmp_path / filename
        p.write_text(content)
        return p
    return _make


class TestParseClasses:
    def test_single_class(self, tmp_py):
        result = parse_file(tmp_py("models.py", """
class User:
    '''A user.'''
    pass
"""))
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "User"
        assert result.symbols[0].kind == SymbolKind.CLASS
        assert result.symbols[0].docstring == "A user."

    def test_multiple_classes(self, tmp_py):
        result = parse_file(tmp_py("models.py", """
class User:
    pass

class Post:
    pass

class Comment:
    pass
"""))
        names = [s.name for s in result.symbols]
        assert names == ["User", "Post", "Comment"]

    def test_private_class_ignored(self, tmp_py):
        result = parse_file(tmp_py("models.py", """
class _Internal:
    pass

class Public:
    pass
"""))
        # _Internal is present in symbols (filtering happens in generator)
        names = [s.name for s in result.symbols]
        assert "_Internal" in names
        assert "Public" in names

    def test_decorated_class(self, tmp_py):
        result = parse_file(tmp_py("models.py", """
from autoexport import export

@export
class User:
    pass

class Other:
    pass
"""))
        user = [s for s in result.symbols if s.name == "User"][0]
        other = [s for s in result.symbols if s.name == "Other"][0]
        assert user.has_export_decorator is True
        assert other.has_export_decorator is False

    def test_dataclass(self, tmp_py):
        result = parse_file(tmp_py("models.py", """
from dataclasses import dataclass

@dataclass
class Point:
    x: float
    y: float
"""))
        assert result.symbols[0].name == "Point"
        assert result.symbols[0].kind == SymbolKind.CLASS


class TestParseFunctions:
    def test_regular_function(self, tmp_py):
        result = parse_file(tmp_py("utils.py", """
def greet(name: str) -> str:
    '''Greet someone.'''
    return f"Hello, {name}!"
"""))
        assert result.symbols[0].name == "greet"
        assert result.symbols[0].kind == SymbolKind.FUNCTION
        assert result.symbols[0].docstring == "Greet someone."

    def test_async_function(self, tmp_py):
        result = parse_file(tmp_py("utils.py", """
async def fetch_data(url: str):
    pass
"""))
        assert result.symbols[0].name == "fetch_data"
        assert result.symbols[0].kind == SymbolKind.FUNCTION

    def test_decorated_function(self, tmp_py):
        result = parse_file(tmp_py("utils.py", """
from autoexport import export

@export
def public_fn():
    pass

def internal_fn():
    pass
"""))
        pub = [s for s in result.symbols if s.name == "public_fn"][0]
        priv = [s for s in result.symbols if s.name == "internal_fn"][0]
        assert pub.has_export_decorator is True
        assert priv.has_export_decorator is False


class TestParseConstants:
    def test_upper_case_constant(self, tmp_py):
        result = parse_file(tmp_py("config.py", """
MAX_RETRIES = 3
DEBUG = True
API_URL = "https://api.example.com"
"""))
        names = [s.name for s in result.symbols]
        assert "MAX_RETRIES" in names
        assert "DEBUG" in names
        assert "API_URL" in names
        for s in result.symbols:
            assert s.kind == SymbolKind.CONSTANT

    def test_lowercase_variable(self, tmp_py):
        result = parse_file(tmp_py("config.py", """
default_name = "world"
"""))
        assert result.symbols[0].kind == SymbolKind.VARIABLE

    def test_annotated_assignment(self, tmp_py):
        result = parse_file(tmp_py("config.py", """
PORT: int = 8080
"""))
        assert result.symbols[0].name == "PORT"
        assert result.symbols[0].kind == SymbolKind.CONSTANT


class TestParseAll:
    def test_explicit_all(self, tmp_py):
        result = parse_file(tmp_py("models.py", """
__all__ = ["User", "Post"]

class User:
    pass

class Post:
    pass

class Internal:
    pass
"""))
        assert result.has_explicit_all is True
        assert result.explicit_all == ["User", "Post"]

    def test_all_as_tuple(self, tmp_py):
        result = parse_file(tmp_py("models.py", """
__all__ = ("User",)

class User:
    pass
"""))
        assert result.explicit_all == ["User"]

    def test_all_dynamic_not_resolved(self, tmp_py):
        result = parse_file(tmp_py("models.py", """
__all__ = get_exports()

class User:
    pass
"""))
        assert result.explicit_all is None


class TestParseEdgeCases:
    def test_syntax_error(self, tmp_py):
        result = parse_file(tmp_py("bad.py", """
def broken(
"""))
        assert result.parse_error is not None
        assert result.symbols == []

    def test_empty_file(self, tmp_py):
        result = parse_file(tmp_py("empty.py", ""))
        assert result.symbols == []
        assert result.parse_error is None

    def test_only_imports(self, tmp_py):
        result = parse_file(tmp_py("imports.py", """
import os
from pathlib import Path
"""))
        assert result.symbols == []

    def test_module_name_from_filename(self, tmp_py):
        result = parse_file(tmp_py("my_module.py", ""))
        assert result.module_name == "my_module"

    def test_nested_class_not_included(self, tmp_py):
        """Only top-level classes should be parsed."""
        result = parse_file(tmp_py("models.py", """
class Outer:
    class Inner:
        pass
"""))
        names = [s.name for s in result.symbols]
        assert "Outer" in names
        assert "Inner" not in names  # ast.iter_child_nodes only gets top-level
