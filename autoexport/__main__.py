"""Allow running as `python -m autoexport`."""
import sys
from .cli import main
sys.exit(main())
