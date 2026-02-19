"""
CLI for autoexport.

Usage:
    autoexport init                    # Create autoexport.toml with defaults
    autoexport generate                # One-shot generation
    autoexport generate --dry-run      # Preview what would be generated
    autoexport generate --diff         # Show diff of what would change
    autoexport watch                   # Watch and regenerate on save
    autoexport clean                   # Remove all auto-generated __init__.py files
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import Config, ExportMode, ImportStyle, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="autoexport",
        description="Auto-generate __init__.py files from your source code.",
    )
    parser.add_argument(
        "-c", "--config",
        help="Path to config file (default: autoexport.toml or pyproject.toml)",
        default=None,
    )
    sub = parser.add_subparsers(dest="command")

    # ── init ──
    init_parser = sub.add_parser("init", help="Create autoexport.toml with defaults")
    init_parser.add_argument(
        "--watch", nargs="+", default=None,
        help="Directories to watch (e.g. --watch src/app src/lib)",
    )

    # ── generate ──
    gen_parser = sub.add_parser("generate", help="One-shot __init__.py generation")
    gen_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be generated without writing files",
    )
    gen_parser.add_argument(
        "--diff", action="store_true",
        help="Show a unified diff of what would change",
    )
    gen_parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show detailed output",
    )

    # ── watch ──
    watch_parser = sub.add_parser("watch", help="Watch directories and regenerate on save")
    watch_parser.add_argument(
        "--poll-interval", type=float, default=0.5,
        help="Polling interval in seconds (default: 0.5)",
    )

    # ── clean ──
    sub.add_parser("clean", help="Remove all auto-generated __init__.py files")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "init":
        return cmd_init(args)

    # Load config for all other commands
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    if args.command == "generate":
        return cmd_generate(config, args)
    elif args.command == "watch":
        return cmd_watch(config, args)
    elif args.command == "clean":
        return cmd_clean(config)

    return 0


def cmd_init(args) -> int:
    """Create a default autoexport.toml."""
    target = Path("autoexport.toml")
    if target.exists():
        print(f"Error: {target} already exists.", file=sys.stderr)
        return 1

    watch_dirs = args.watch or ["."]
    watch_str = ", ".join(f'"{d}"' for d in watch_dirs)

    content = f"""[autoexport]
# Directories to watch and generate __init__.py for
watch = [{watch_str}]

# Directories to skip
exclude_dirs = ["__pycache__", ".git", ".venv", "venv", "node_modules"]

# Files to skip
exclude_files = ["conftest.py", "setup.py"]

# Export mode:
#   "all"       — export all public classes, functions, and constants
#   "public"    — export classes and functions only (no constants/variables)
#   "decorated" — only export items marked with @export
mode = "all"

# Import style:
#   "relative" — from .module import Name (default)
#   "absolute" — from package.module import Name
import_style = "relative"

# Whether to export UPPER_CASE constants
export_constants = true

# Whether to export non-constant variables
export_variables = false

# Bubble up child package exports to parent __init__.py
# e.g. makes `from app import User` work when User is in app/models/user.py
flatten = false

# Use PEP 562 lazy imports (__getattr__) for faster startup
lazy = false

# Format generated files with black (requires black to be installed)
use_black = false

# Recurse into subdirectories
recursive = true

# If a file defines __all__, respect it instead of auto-detecting
respect_existing_all = true
"""

    target.write_text(content)
    print(f"Created {target}")
    print(f"Watching: {', '.join(watch_dirs)}")
    print(f"\nRun 'autoexport generate' to generate __init__.py files.")
    print(f"Run 'autoexport watch' to auto-regenerate on save.")
    return 0


def cmd_generate(config: Config, args) -> int:
    """One-shot generation."""
    from .generator import generate_all, write_results, diff_results

    results = generate_all(config)

    # Diff mode
    if args.diff:
        diffs = diff_results(results)
        if not diffs:
            print("  No changes.")
            return 0
        for path, diff_text in diffs:
            print(diff_text)
        return 0

    written = write_results(results, dry_run=args.dry_run)

    if args.dry_run:
        prefix = "[dry-run] "
    else:
        prefix = ""

    # Report
    for result in results:
        if result.error:
            print(f"  ⚠ {result.directory}: {result.error}", file=sys.stderr)
            continue

        init_path = result.directory / "__init__.py"
        n = len(result.imports)
        n_sub = len(result.subpackages)

        if init_path in written:
            parts = []
            if n:
                parts.append(f"{n} exports")
            if n_sub:
                parts.append(f"{n_sub} subpackages")
            detail = ", ".join(parts) or "empty"
            print(f"  {prefix}✓ {init_path} ({detail})")
        elif args.verbose:
            print(f"  — {init_path} (unchanged)")

    if not written:
        print("  No changes needed.")

    total = sum(len(r.imports) for r in results if not r.error)
    dirs = sum(1 for r in results if not r.error)
    print(f"\n  {total} exports across {dirs} packages.")

    return 0


def cmd_watch(config: Config, args) -> int:
    """Watch and regenerate."""
    from .watcher import watch

    print("autoexport — watching for changes...\n")
    try:
        watch(config, poll_interval=args.poll_interval)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_clean(config: Config) -> int:
    """Remove all auto-generated __init__.py files."""
    from .generator import _collect_directories, _is_autoexport_managed

    removed = 0
    for watch_path in config.watch_paths:
        if not watch_path.exists():
            continue
        dirs = _collect_directories(watch_path, config)
        for d in dirs:
            init_path = d / "__init__.py"
            if init_path.exists() and _is_autoexport_managed(init_path):
                init_path.unlink()
                print(f"  ✓ Removed {init_path}")
                removed += 1

    if removed:
        print(f"\n  Removed {removed} auto-generated __init__.py files.")
    else:
        print("  No auto-generated __init__.py files found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
