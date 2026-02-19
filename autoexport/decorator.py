"""
Optional @export decorator for use with mode = "decorated".

When autoexport is configured with mode = "decorated", only items marked
with @export will be included in the generated __init__.py.

Usage:
    from autoexport import export

    @export
    class User:
        pass

    @export
    def helper():
        pass

    class InternalThing:  # NOT exported
        pass
"""

from typing import TypeVar

T = TypeVar("T")


def export(obj: T) -> T:
    """
    Mark a class or function for export.

    This is a no-op decorator — it just returns the object unchanged.
    Autoexport's parser detects it via AST inspection (it doesn't execute
    your code), so the decorator's only job is to be a visible marker.
    """
    return obj
