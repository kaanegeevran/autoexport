"""
Generator that scans directories and produces __init__.py files.

This is the core of autoexport. It:
1. Scans a directory for .py files
2. Parses each file to find exportable symbols
3. Filters based on config (mode, constants, variables, etc.)
4. Generates a clean __init__.py with proper imports and __all__

Supports:
- Flatten/bubble-up: re-export child package symbols at parent level
- Lazy imports: PEP 562 __getattr__ + __dir__ based deferred loading
- Absolute imports: from package.module import Name
- Black formatting: auto-format generated files
- Diff mode: show what would change without writing
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import Config, ExportMode, ImportStyle
from .parser import ParseResult, Symbol, SymbolKind, parse_file


GENERATED_MARKER = "# [autoexport]"


@dataclass
class ImportLine:
    """A single import line to include in __init__.py."""
    module_name: str
    symbol_name: str
    kind: SymbolKind
    is_subpackage_reexport: bool = False
    """True if this import comes from a child subpackage (flatten mode)."""

    def statement(self, style: ImportStyle = ImportStyle.RELATIVE, package_name: str = "") -> str:
        if style == ImportStyle.ABSOLUTE and package_name:
            return f"from {package_name}.{self.module_name} import {self.symbol_name}"
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


def generate_for_directory(
    directory: Path,
    config: Config,
    package_name: str = "",
) -> GenerateResult:
    """
    Generate the __init__.py content for a single directory.

    Args:
        directory: The directory to scan.
        config: Export configuration.
        package_name: Dotted package name for absolute imports (e.g. "app.models").

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

    # Flatten: bubble up child exports to this level
    if config.flatten and subpackages:
        for subpkg in subpackages:
            child_dir = directory / subpkg
            child_pkg_name = f"{package_name}.{subpkg}" if package_name else subpkg
            child_result = generate_for_directory(child_dir, config, child_pkg_name)
            if child_result.error:
                continue
            for child_imp in child_result.imports:
                # Re-export as: from .subpkg.module import Name
                reexport_module = f"{subpkg}.{child_imp.module_name}"
                imports.append(ImportLine(
                    module_name=reexport_module,
                    symbol_name=child_imp.symbol_name,
                    kind=child_imp.kind,
                    is_subpackage_reexport=True,
                ))

    result.imports = imports
    result.subpackages = subpackages
    result.content = _render_init(imports, subpackages, config, package_name)

    # Apply black formatting if requested
    if config.use_black:
        result.content = _format_with_black(result.content)

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
            # Compute the dotted package name for absolute imports
            try:
                rel = d.relative_to(watch_path)
                parts = list(rel.parts)
                pkg_name = ".".join([watch_path.name] + parts) if parts else watch_path.name
            except ValueError:
                pkg_name = d.name

            result = generate_for_directory(d, config, pkg_name)
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


def diff_results(results: list[GenerateResult]) -> list[tuple[Path, str]]:
    """
    Generate unified diffs for all changed files.

    Returns:
        List of (path, diff_text) tuples for files that would change.
    """
    diffs: list[tuple[Path, str]] = []

    for result in results:
        if result.error or not result.changed:
            continue

        init_path = result.directory / "__init__.py"

        if init_path.exists():
            try:
                existing = init_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                existing = ""
        else:
            existing = ""

        if existing == result.content:
            continue

        diff_lines = difflib.unified_diff(
            existing.splitlines(keepends=True),
            result.content.splitlines(keepends=True),
            fromfile=f"a/{init_path}",
            tofile=f"b/{init_path}",
            lineterm="",
        )
        diff_text = "\n".join(diff_lines)
        if diff_text:
            diffs.append((init_path, diff_text))

    return diffs


# ── Internal helpers ──────────────────────────────────────────────────


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
    package_name: str = "",
) -> str:
    """Render the __init__.py content."""

    if config.lazy:
        return _render_lazy_init(imports, subpackages, config, package_name)

    return _render_eager_init(imports, subpackages, config, package_name)


def _render_eager_init(
    imports: list[ImportLine],
    subpackages: list[str],
    config: Config,
    package_name: str = "",
) -> str:
    """Render standard eager-import __init__.py."""
    lines: list[str] = []

    # Header
    lines.append(config.header)
    lines.append(GENERATED_MARKER)
    lines.append("")

    if not imports and not subpackages:
        lines.append("")
        return "\n".join(lines)

    style = config.import_style

    # Group imports by kind for readability
    class_imports = [i for i in imports if i.kind == SymbolKind.CLASS]
    func_imports = [i for i in imports if i.kind == SymbolKind.FUNCTION]
    const_imports = [i for i in imports if i.kind in (SymbolKind.CONSTANT, SymbolKind.VARIABLE)]

    # Subpackage imports (only if not flattened — if flattened, the child
    # exports are already inlined as direct imports above)
    if subpackages:
        for pkg in subpackages:
            if style == ImportStyle.ABSOLUTE and package_name:
                lines.append(f"from {package_name} import {pkg}")
            else:
                lines.append(f"from . import {pkg}")
        lines.append("")

    # Class imports
    if class_imports:
        for imp in class_imports:
            lines.append(imp.statement(style, package_name))
        lines.append("")

    # Function imports
    if func_imports:
        for imp in func_imports:
            lines.append(imp.statement(style, package_name))
        lines.append("")

    # Constant imports
    if const_imports:
        for imp in const_imports:
            lines.append(imp.statement(style, package_name))
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


def _render_lazy_init(
    imports: list[ImportLine],
    subpackages: list[str],
    config: Config,
    package_name: str = "",
) -> str:
    """
    Render a PEP 562 lazy-import __init__.py.

    Instead of importing everything eagerly at module load time, this generates
    a __getattr__ function that imports on first access. This dramatically
    reduces import time for large packages.
    """
    lines: list[str] = []
    style = config.import_style

    # Header
    lines.append(config.header)
    lines.append(GENERATED_MARKER)
    lines.append("")

    if not imports and not subpackages:
        lines.append("")
        return "\n".join(lines)

    # Build the mapping: name -> (module_path, is_subpackage)
    lines.append("import importlib")
    lines.append("")

    # Submodule mapping for subpackages
    if subpackages:
        lines.append("_SUBPACKAGES = {")
        for pkg in subpackages:
            if style == ImportStyle.ABSOLUTE and package_name:
                lines.append(f'    "{pkg}": "{package_name}.{pkg}",')
            else:
                lines.append(f'    "{pkg}": "." + "{pkg}",')
        lines.append("}")
        lines.append("")

    # Attribute mapping: name -> (module_to_import, attr_name)
    lines.append("_LAZY_IMPORTS = {")
    for imp in imports:
        if style == ImportStyle.ABSOLUTE and package_name:
            mod_path = f"{package_name}.{imp.module_name}"
        else:
            mod_path = f".{imp.module_name}"
        lines.append(f'    "{imp.symbol_name}": ("{mod_path}", "{imp.symbol_name}"),')
    lines.append("}")
    lines.append("")

    # __getattr__
    lines.append("")
    lines.append("def __getattr__(name):")
    if subpackages:
        lines.append("    if name in _SUBPACKAGES:")
        lines.append("        module_path = _SUBPACKAGES[name]")
        lines.append('        if module_path.startswith("."):')
        lines.append("            return importlib.import_module(module_path, __name__)")
        lines.append("        return importlib.import_module(module_path)")
    lines.append("    if name in _LAZY_IMPORTS:")
    lines.append("        module_path, attr = _LAZY_IMPORTS[name]")
    lines.append('        if module_path.startswith("."):')
    lines.append("            mod = importlib.import_module(module_path, __name__)")
    lines.append("        else:")
    lines.append("            mod = importlib.import_module(module_path)")
    lines.append("        val = getattr(mod, attr)")
    lines.append("        globals()[name] = val  # Cache for subsequent access")
    lines.append("        return val")
    lines.append('    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")')
    lines.append("")

    # __dir__
    lines.append("")
    lines.append("def __dir__():")
    lines.append("    _all = list(globals().keys())")
    if subpackages:
        lines.append("    _all.extend(_SUBPACKAGES.keys())")
    lines.append("    _all.extend(_LAZY_IMPORTS.keys())")
    lines.append("    return _all")
    lines.append("")

    # __all__
    all_names: list[str] = []
    all_names.extend(pkg for pkg in subpackages)
    all_names.extend(imp.symbol_name for imp in imports)

    if all_names:
        lines.append("")
        lines.append("__all__ = [")
        for name in all_names:
            lines.append(f'    "{name}",')
        lines.append("]")
        lines.append("")

    return "\n".join(lines)


def _format_with_black(content: str) -> str:
    """Format Python source with black. Falls back to unformatted if black is not installed."""
    try:
        import black
        mode = black.Mode(line_length=88)
        return black.format_str(content, mode=mode)
    except ImportError:
        return content
    except Exception:
        # Don't crash if black chokes on our output
        return content


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
