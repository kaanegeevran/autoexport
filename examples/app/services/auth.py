"""Authentication service."""


class AuthService:
    """Handles user authentication."""

    def __init__(self):
        self.sessions: dict[str, str] = {}

    def login(self, username: str, password: str) -> bool:
        """Authenticate a user."""
        # Dummy auth
        self.sessions[username] = "active"
        return True

    def logout(self, username: str) -> None:
        """End a user's session."""
        self.sessions.pop(username, None)
