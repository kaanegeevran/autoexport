# autoexport

**Auto-generate `__init__.py` files on save. Full IDE support, zero boilerplate.**

Stop writing and maintaining `__init__.py` files by hand. `autoexport` watches your source files and generates them for you — with proper imports, `__all__`, and full IDE autocomplete.

## Before

```python
# app/models/__init__.py — you maintain this manually
from .user import User
from .post import Post
from .comment import Comment

__all__ = ["User", "Post", "Comment"]
```

Every time you add a class, rename one, or delete a file — you have to update `__init__.py`. Forget once, get `ImportError`.

## After

```bash
autoexport watch
```

That's it. The `__init__.py` files are generated and kept in sync automatically.

---

## Install

```bash
# pip
pip install git+https://github.com/kaanegeevran/autoexport.git

# uv
uv add git+https://github.com/kaanegeevran/autoexport.git

# With extras (file watcher, black formatting, or everything)
pip install "autoexport[watch] @ git+https://github.com/kaanegeevran/autoexport.git"
pip install "autoexport[black] @ git+https://github.com/kaanegeevran/autoexport.git"
pip install "autoexport[all] @ git+https://github.com/kaanegeevran/autoexport.git"

uv add "autoexport[watch] @ git+https://github.com/kaanegeevran/autoexport.git"
uv add "autoexport[black] @ git+https://github.com/kaanegeevran/autoexport.git"
uv add "autoexport[all] @ git+https://github.com/kaanegeevran/autoexport.git"
```

## Quick Start

```bash
# 1. Create config
autoexport init --watch src/app

# 2. Generate __init__.py files (one-shot)
autoexport generate

# 3. Or watch and auto-regenerate on every save
autoexport watch
```

## Configuration

Create `autoexport.toml` in your project root (or use `[tool.autoexport]` in `pyproject.toml`):

```toml
[autoexport]
# Directories to watch
watch = ["src/app", "src/lib"]

# What to export:
#   "all"       — classes, functions, and UPPER_CASE constants (default)
#   "public"    — classes and functions only
#   "decorated" — only items marked with @export
mode = "all"

# Import style:
#   "relative" — from .module import Name (default)
#   "absolute" — from package.module import Name
import_style = "relative"

# Fine-grained control
export_constants = true      # Include UPPER_CASE assignments
export_variables = false     # Include lowercase assignments

# Bubble up child package exports to parent __init__.py
# Makes `from app import User` work when User is in app/models/user.py
flatten = false

# Use PEP 562 lazy imports for faster startup (large packages)
lazy = false

# Format generated files with black (requires: pip install black)
use_black = false

# Directories and files to skip
exclude_dirs = ["__pycache__", ".git", ".venv", "tests"]
exclude_files = ["conftest.py", "setup.py"]

# Recurse into subdirectories
recursive = true

# If a file defines __all__, respect it instead of auto-detecting
respect_existing_all = true
```

## Features

### Flatten / Bubble-up exports

With `flatten = true`, child package exports are re-exported at the parent level:

```python
# Without flatten:
from app.models import User       # must know the subpackage

# With flatten:
from app import User              # works — bubbled up from app/models/user.py
from app.models import User       # also still works
```

Generated `app/__init__.py`:
```python
from . import models
from . import services
from .models.user import User
from .models.post import Post
from .services.auth import AuthService
```

### Lazy imports (PEP 562)

With `lazy = true`, imports are deferred until first access. This dramatically reduces import time for large packages:

```python
# Generated __init__.py uses __getattr__ instead of direct imports:
def __getattr__(name):
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(module_path, __name__)
        val = getattr(mod, attr)
        globals()[name] = val  # cached after first access
        return val
    raise AttributeError(...)
```

Usage is identical — `from app.models import User` still works, it's just loaded on first use.

### Absolute imports

With `import_style = "absolute"`, generates fully qualified imports:

```python
# relative (default):
from .user import User

# absolute:
from mypackage.models.user import User
```

### Export modes

**`mode = "all"` (default)** — exports everything public:

```python
class User: ...        # ✓ exported
def helper(): ...      # ✓ exported
MAX_RETRIES = 3        # ✓ exported (constant)
_internal = "x"        # ✗ private, skipped
```

**`mode = "public"`** — classes and functions only:

```python
class User: ...        # ✓ exported
def helper(): ...      # ✓ exported
MAX_RETRIES = 3        # ✗ skipped
```

**`mode = "decorated"`** — only `@export`-marked items:

```python
from autoexport import export

@export
class User: ...        # ✓ exported
class Internal: ...    # ✗ skipped
```

### Diff mode

Preview what would change before writing:

```bash
autoexport generate --diff
```

Shows a unified diff of every `__init__.py` that would be modified.

### Black formatting

With `use_black = true` (and `black` installed), generated files are auto-formatted.

## Commands

| Command | Description |
|---------|-------------|
| `autoexport init` | Create `autoexport.toml` with defaults |
| `autoexport generate` | One-shot generation |
| `autoexport generate --dry-run` | Preview without writing |
| `autoexport generate --diff` | Show unified diff of changes |
| `autoexport watch` | Watch and regenerate on save |
| `autoexport clean` | Remove all auto-generated `__init__.py` files |

## How It Works

1. Scans your `.py` files using Python's `ast` module (no code execution)
2. Extracts top-level classes, functions, and constants
3. Generates `__init__.py` with proper `from .module import Name` lines
4. Includes `__all__` for explicit public API
5. Only overwrites files it previously generated (marked with `# [autoexport]`)
6. Never touches hand-written `__init__.py` files

## Safety

- **Never overwrites hand-written `__init__.py` files.** Only files containing the `# [autoexport]` marker are managed.
- **AST-only parsing.** Your code is never executed during generation.
- **Syntax errors are skipped.** A broken file won't break generation for the rest of the directory.
- **`autoexport clean`** removes only auto-generated files.

## IDE Integration

### VS Code

Add to `.vscode/tasks.json` to run on build:

```json
{
    "label": "autoexport",
    "type": "shell",
    "command": "autoexport watch",
    "isBackground": true,
    "problemMatcher": []
}
```

Or use the Run on Save extension to trigger `autoexport generate` on file save.

### PyCharm

Use a File Watcher (Settings → Tools → File Watchers) with:
- Program: `autoexport`
- Arguments: `generate`
- Working directory: `$ProjectFileDir$`

## License

MIT
