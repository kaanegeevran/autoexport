"""
Example: using your app after autoexport generates __init__.py files.

First run:
    cd examples
    autoexport generate

Then:
    python main.py

You'll see that all imports work cleanly — no manual __init__.py needed.
"""

# These "just work" after autoexport generates the __init__.py files:
from app.models import User, Post
from app.services import AuthService
from app.controllers import APIController
from app import config

def main():
    # Full IDE autocomplete on all of these
    alice = User(name="Alice", email="alice@example.com")
    print(alice.greet())

    post = Post(title="Hello World", body="My first post", author_name="Alice")
    print(post.summary())

    auth = AuthService()
    auth.login("alice", "password123")
    print(f"Sessions: {auth.sessions}")

    ctrl = APIController()
    print(ctrl.handle_request("/api/users"))

    print(f"\nApp: {config.APP_NAME} (debug={config.DEBUG})")


if __name__ == "__main__":
    main()
