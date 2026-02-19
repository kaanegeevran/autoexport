"""Blog post model."""

from dataclasses import dataclass


@dataclass
class Post:
    """A blog post."""
    title: str
    body: str
    author_name: str = ""

    def summary(self) -> str:
        """Short summary of the post."""
        return f'"{self.title}" by {self.author_name or "anonymous"}'
