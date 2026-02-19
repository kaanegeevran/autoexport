"""
AST-based parser that extracts exportable symbols from Python source files.

Extracts:
- Top-level classes
- Top-level functions
- Top-level constants (UPPER_CASE assignments)
- Items explicitly listed in __all__
- Items decorated with @export (optional opt-in mode)

Does NOT export:
- Private names (starting with _)
- Imports (re-exports are handled separately)
- Nested classes/functions
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class SymbolKind(Enum):
    CLASS = "class"
    FUNCTION = "function"
    CONSTANT = "constant"
    VARIABLE = "variable"


@dataclass
class Symbol:
    """A single exportable symbol found in a source file."""
    name: str
    kind: SymbolKind
    lineno: int
    has_export_decorator: bool = False
    docstring: Optional[str] = None


@dataclass
class ParseResult:
    """Result of parsing a single Python file."""
    filepath: Path
    module_name: str
    symbols: list[Symbol] = field(default_factory=list)
    explicit_all: Optional[list[str]] = None  # If __all__ is defined
    parse_error: Optional[str] = None

    @property
    def has_explicit_all(self) -> bool:
        return self.explicit_all is not None


def parse_file(filepath: Path, export_decorator: str = "export") -> ParseResult:
    """
    Parse a Python file and extract all exportable symbols.

    Args:
        filepath: Path to the .py file.
        export_decorator: Name of the decorator that marks explicit exports.

    Returns:
        ParseResult with all discovered symbols.
    """
    module_name = filepath.stem
    result = ParseResult(filepath=filepath, module_name=module_name)

    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        result.parse_error = f"Cannot read file: {e}"
        return result

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        result.parse_error = f"Syntax error: {e}"
        return result

    for node in ast.iter_child_nodes(tree):
        # Classes
        if isinstance(node, ast.ClassDef):
            result.symbols.append(Symbol(
                name=node.name,
                kind=SymbolKind.CLASS,
                lineno=node.lineno,
                has_export_decorator=_has_decorator(node, export_decorator),
                docstring=ast.get_docstring(node),
            ))

        # Functions
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.symbols.append(Symbol(
                name=node.name,
                kind=SymbolKind.FUNCTION,
                lineno=node.lineno,
                has_export_decorator=_has_decorator(node, export_decorator),
                docstring=ast.get_docstring(node),
            ))

        # Assignments — constants (UPPER_CASE) and variables
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names = _extract_assign_names(target)
                for name in names:
                    if name == "__all__":
                        result.explicit_all = _extract_all_value(node.value)
                    elif not name.startswith("_"):
                        kind = (
                            SymbolKind.CONSTANT
                            if name.isupper() or _is_screaming_snake(name)
                            else SymbolKind.VARIABLE
                        )
                        result.symbols.append(Symbol(
                            name=name,
                            kind=kind,
                            lineno=node.lineno,
                        ))

        # Annotated assignments: x: int = 5
        elif isinstance(node, ast.AnnAssign) and node.target and node.value:
            if isinstance(node.target, ast.Name):
                name = node.target.id
                if name != "__all__" and not name.startswith("_"):
                    kind = (
                        SymbolKind.CONSTANT
                        if name.isupper() or _is_screaming_snake(name)
                        else SymbolKind.VARIABLE
                    )
                    result.symbols.append(Symbol(
                        name=name,
                        kind=kind,
                        lineno=node.lineno,
                    ))

    return result


def _has_decorator(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
                   decorator_name: str) -> bool:
    """Check if a class/function has a specific decorator."""
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == decorator_name:
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == decorator_name:
            return True
    return False


def _extract_assign_names(target: ast.expr) -> list[str]:
    """Extract variable names from an assignment target."""
    if isinstance(target, ast.Name):
        return [target.id]
    elif isinstance(target, ast.Tuple):
        names = []
        for elt in target.elts:
            names.extend(_extract_assign_names(elt))
        return names
    return []


def _extract_all_value(node: ast.expr) -> Optional[list[str]]:
    """Try to statically extract the value of __all__ = [...]."""
    if isinstance(node, (ast.List, ast.Tuple)):
        names = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.append(elt.value)
            else:
                return None  # Can't statically resolve
        return names
    return None


def _is_screaming_snake(name: str) -> bool:
    """Check if a name is SCREAMING_SNAKE_CASE (constant convention)."""
    return bool(name) and all(
        c.isupper() or c == "_" or c.isdigit() for c in name
    ) and any(c.isalpha() for c in name)
