"""
Generator that scans directories and produces __init__.py files.

This is the core of autoexport. It:
1. Scans a directory for .py files
2. Parses each file to find exportable symbols
3. Filters based on config (mode, constants, variables, etc.)
4. Generates a clean __init__.py with proper imports and __all__
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config, ExportMode
from .parser import ParseResult, Symbol, SymbolKind, parse_file


GENERATED_MARKER = "# [autoexport]"


@dataclass
class ImportLine:
    """A single import line to include in __init__.py."""
    module_name: str
    symbol_name: str
    kind: SymbolKind

    @property
    def statement(self) -> str:
        return f"from .{self.module_name} import {self.symbol_name}"


@dataclass
class GenerateResult:
    """Result of generating an __init__.py for a single directory."""
    directory: Path
    imports: list[ImportLine] = field(default_factory=list)
    subpackages: list[str] = field(default_factory=list)
    content: str = ""
    changed: bool = False
    error: Optional[str] = None


def generate_for_directory(directory: Path, config: Config) -> GenerateResult:
    """
    Generate the __init__.py content for a single directory.

    Args:
        directory: The directory to scan.
        config: Export configuration.

    Returns:
        GenerateResult with the generated content and metadata.
    """
    result = GenerateResult(directory=directory)

    if not directory.is_dir():
        result.error = f"Not a directory: {directory}"
        return result

    imports: list[ImportLine] = []
    subpackages: list[str] = []

    # Scan .py files in this directory
    py_files = sorted(
        f for f in directory.iterdir()
        if f.is_file()
        and f.suffix == ".py"
        and f.name != "__init__.py"
        and f.name not in config.exclude_files
        and not f.name.startswith("_")
    )

    for py_file in py_files:
        parsed = parse_file(py_file, export_decorator=config.export_decorator)

        if parsed.parse_error:
            # Skip files with errors, but don't fail the whole directory
            continue

        symbols = _filter_symbols(parsed, config)

        for sym in symbols:
            imports.append(ImportLine(
                module_name=parsed.module_name,
                symbol_name=sym.name,
                kind=sym.kind,
            ))

    # Scan subdirectories (subpackages)
    if config.recursive:
        for item in sorted(directory.iterdir()):
            if (
                item.is_dir()
                and item.name not in config.exclude_dirs
                and not item.name.startswith("_")
                and not item.name.startswith(".")
            ):
                subpackages.append(item.name)

    result.imports = imports
    result.subpackages = subpackages
    result.content = _render_init(imports, subpackages, config)

    # Check if it actually changed
    init_path = directory / "__init__.py"
    if init_path.exists():
        try:
            existing = init_path.read_text(encoding="utf-8")
            result.changed = existing != result.content
        except (OSError, UnicodeDecodeError):
            result.changed = True
    else:
        result.changed = True

    return result


def generate_all(config: Config) -> list[GenerateResult]:
    """
    Generate __init__.py files for all configured directories.

    If recursive, also generates for all subdirectories.
    """
    results: list[GenerateResult] = []

    for watch_path in config.watch_paths:
        if not watch_path.exists():
            results.append(GenerateResult(
                directory=watch_path,
                error=f"Directory does not exist: {watch_path}",
            ))
            continue

        dirs_to_process = _collect_directories(watch_path, config)
        for d in dirs_to_process:
            result = generate_for_directory(d, config)
            results.append(result)

    return results


def write_results(results: list[GenerateResult], dry_run: bool = False) -> list[Path]:
    """
    Write generated __init__.py files to disk.

    Args:
        results: List of GenerateResult from generate_all.
        dry_run: If True, don't actually write files.

    Returns:
        List of paths that were written (or would have been).
    """
    written: list[Path] = []

    for result in results:
        if result.error:
            continue
        if not result.changed:
            continue

        init_path = result.directory / "__init__.py"

        # Safety: don't overwrite a hand-written __init__.py
        if init_path.exists() and not _is_autoexport_managed(init_path):
            continue

        if not dry_run:
            init_path.write_text(result.content, encoding="utf-8")

        written.append(init_path)

    return written


def _filter_symbols(parsed: ParseResult, config: Config) -> list[Symbol]:
    """Filter symbols based on config mode and settings."""

    # If the file has __all__ and we respect it, use that
    if config.respect_existing_all and parsed.has_explicit_all:
        allowed = set(parsed.explicit_all)  # type: ignore
        return [s for s in parsed.symbols if s.name in allowed]

    symbols = []
    for sym in parsed.symbols:
        # Skip private names
        if sym.name.startswith("_"):
            continue

        # Mode filtering
        if config.mode == ExportMode.DECORATED:
            if not sym.has_export_decorator:
                continue
        elif config.mode == ExportMode.PUBLIC:
            if sym.kind in (SymbolKind.CONSTANT, SymbolKind.VARIABLE):
                continue  # PUBLIC mode only exports classes and functions
        elif config.mode == ExportMode.ALL:
            if sym.kind == SymbolKind.CONSTANT and not config.export_constants:
                continue
            if sym.kind == SymbolKind.VARIABLE and not config.export_variables:
                continue

        symbols.append(sym)

    return symbols


def _render_init(
    imports: list[ImportLine],
    subpackages: list[str],
    config: Config,
) -> str:
    """Render the __init__.py content."""
    lines: list[str] = []

    # Header
    lines.append(config.header)
    lines.append(GENERATED_MARKER)
    lines.append("")

    if not imports and not subpackages:
        lines.append("")
        return "\n".join(lines)

    # Group imports by kind for readability
    class_imports = [i for i in imports if i.kind == SymbolKind.CLASS]
    func_imports = [i for i in imports if i.kind == SymbolKind.FUNCTION]
    const_imports = [i for i in imports if i.kind in (SymbolKind.CONSTANT, SymbolKind.VARIABLE)]

    # Subpackage imports
    if subpackages:
        for pkg in subpackages:
            lines.append(f"from . import {pkg}")
        lines.append("")

    # Class imports
    if class_imports:
        for imp in class_imports:
            lines.append(imp.statement)
        lines.append("")

    # Function imports
    if func_imports:
        for imp in func_imports:
            lines.append(imp.statement)
        lines.append("")

    # Constant imports
    if const_imports:
        for imp in const_imports:
            lines.append(imp.statement)
        lines.append("")

    # __all__
    all_names: list[str] = []
    all_names.extend(pkg for pkg in subpackages)
    all_names.extend(imp.symbol_name for imp in imports)

    if all_names:
        lines.append("__all__ = [")
        for name in all_names:
            lines.append(f'    "{name}",')
        lines.append("]")
        lines.append("")

    return "\n".join(lines)


def _is_autoexport_managed(init_path: Path) -> bool:
    """Check if an __init__.py was generated by autoexport."""
    try:
        content = init_path.read_text(encoding="utf-8")
        return GENERATED_MARKER in content
    except (OSError, UnicodeDecodeError):
        return False


def _collect_directories(root: Path, config: Config) -> list[Path]:
    """Collect all directories that should have __init__.py generated."""
    dirs = [root]

    if config.recursive:
        for dirpath, dirnames, _ in os.walk(root):
            # Filter out excluded directories in-place (prevents os.walk from descending)
            dirnames[:] = [
                d for d in sorted(dirnames)
                if d not in config.exclude_dirs
                and not d.startswith("_")
                and not d.startswith(".")
            ]
            for d in dirnames:
                dirs.append(Path(dirpath) / d)

    return sorted(dirs)
