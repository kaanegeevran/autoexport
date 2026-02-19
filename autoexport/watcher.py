"""
File watcher that monitors directories and regenerates __init__.py on changes.

Uses a polling approach for maximum compatibility (no OS-specific deps).
Optionally uses `watchdog` if installed for better performance.
"""

from __future__ import annotations

import os
import sys
import time
import hashlib
from pathlib import Path
from typing import Callable, Optional

from .config import Config
from .generator import generate_for_directory, write_results, _collect_directories


def watch(
    config: Config,
    on_change: Optional[Callable[[list[Path]], None]] = None,
    poll_interval: float = 0.5,
) -> None:
    """
    Watch configured directories and regenerate __init__.py on changes.

    This function blocks forever (until KeyboardInterrupt).

    Args:
        config: Autoexport configuration.
        on_change: Optional callback when files are regenerated.
                   Receives list of written __init__.py paths.
        poll_interval: Seconds between polls (only for polling mode).
    """
    # Try watchdog first for efficiency
    try:
        _watch_with_watchdog(config, on_change)
    except ImportError:
        _watch_with_polling(config, on_change, poll_interval)


def _watch_with_polling(
    config: Config,
    on_change: Optional[Callable[[list[Path]], None]],
    poll_interval: float,
) -> None:
    """Simple polling-based watcher."""
    print("Using polling watcher (install 'watchdog' for better performance)")
    print(f"Watching: {', '.join(config.watch)}")
    print(f"Poll interval: {poll_interval}s")
    print("Press Ctrl+C to stop.\n")

    # Initial snapshot
    snapshot = _take_snapshot(config)

    # Initial generation
    _run_generation(config, on_change)

    try:
        while True:
            time.sleep(poll_interval)
            new_snapshot = _take_snapshot(config)

            if new_snapshot != snapshot:
                changed_files = set(new_snapshot.keys()) ^ set(snapshot.keys())
                changed_files |= {
                    f for f in new_snapshot
                    if f in snapshot and new_snapshot[f] != snapshot[f]
                }

                # Filter to only .py files (not __init__.py)
                relevant = [
                    f for f in changed_files
                    if f.endswith(".py") and not f.endswith("__init__.py")
                ]

                if relevant:
                    _run_generation(config, on_change)

                snapshot = new_snapshot

    except KeyboardInterrupt:
        print("\nStopped watching.")


def _watch_with_watchdog(
    config: Config,
    on_change: Optional[Callable[[list[Path]], None]],
) -> None:
    """Watchdog-based watcher (more efficient, requires `watchdog` package)."""
    from watchdog.observers import Observer  # type: ignore
    from watchdog.events import FileSystemEventHandler, FileSystemEvent  # type: ignore

    print("Using watchdog watcher")
    print(f"Watching: {', '.join(config.watch)}")
    print("Press Ctrl+C to stop.\n")

    # Initial generation
    _run_generation(config, on_change)

    # Debounce: track last generation time per directory
    last_gen: dict[str, float] = {}
    debounce_seconds = 0.3

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                return

            src = str(getattr(event, "src_path", ""))
            if not src.endswith(".py"):
                return
            if src.endswith("__init__.py"):
                return

            # Debounce
            dir_path = str(Path(src).parent)
            now = time.time()
            if dir_path in last_gen and (now - last_gen[dir_path]) < debounce_seconds:
                return
            last_gen[dir_path] = now

            _run_generation(config, on_change)

    observer = Observer()
    handler = Handler()

    for watch_path in config.watch_paths:
        if watch_path.exists():
            observer.schedule(handler, str(watch_path), recursive=config.recursive)

    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nStopped watching.")
    observer.join()


def _run_generation(
    config: Config,
    on_change: Optional[Callable[[list[Path]], None]],
) -> None:
    """Run a full generation pass and report results."""
    from .generator import generate_all

    results = generate_all(config)
    written = write_results(results)

    if written:
        timestamp = time.strftime("%H:%M:%S")
        for path in written:
            # Count imports in the result
            matching = [r for r in results if r.directory == path.parent]
            n_imports = len(matching[0].imports) if matching else 0
            n_subpkg = len(matching[0].subpackages) if matching else 0
            parts = []
            if n_imports:
                parts.append(f"{n_imports} exports")
            if n_subpkg:
                parts.append(f"{n_subpkg} subpackages")
            detail = ", ".join(parts) or "empty"
            print(f"  [{timestamp}] ✓ {path} ({detail})")

        if on_change:
            on_change(written)

    for r in results:
        if r.error:
            print(f"  ⚠ {r.directory}: {r.error}", file=sys.stderr)


def _take_snapshot(config: Config) -> dict[str, str]:
    """
    Take a snapshot of all .py files (path → content hash).
    Used for change detection in polling mode.
    """
    snapshot: dict[str, str] = {}

    for watch_path in config.watch_paths:
        if not watch_path.exists():
            continue

        dirs = _collect_directories(watch_path, config)
        for d in dirs:
            for f in d.iterdir():
                if (
                    f.is_file()
                    and f.suffix == ".py"
                    and f.name != "__init__.py"
                    and f.name not in config.exclude_files
                ):
                    try:
                        content = f.read_bytes()
                        h = hashlib.md5(content).hexdigest()
                        snapshot[str(f)] = h
                    except OSError:
                        pass

    return snapshot
