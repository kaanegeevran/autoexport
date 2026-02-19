"""
autoexport — Auto-generate __init__.py files on save.

Quick start:
    1. cd your-project
    2. autoexport init --watch src/app
    3. autoexport watch

Your __init__.py files are now auto-generated and always in sync.
Full IDE autocomplete, docstrings, and type hints — for free.
"""

__version__ = "0.2.0"

from .decorator import export
from .config import Config, ExportMode, ImportStyle

__all__ = ["export", "Config", "ExportMode", "ImportStyle"]
