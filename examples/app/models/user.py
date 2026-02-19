"""User model."""

from dataclasses import dataclass


@dataclass
class User:
    """A user in the system."""
    name: str
    email: str
    active: bool = True

    def greet(self) -> str:
        """Return a greeting message."""
        return f"Hi, I'm {self.name}!"
