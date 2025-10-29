"""Environment helpers for Praeparo runtimes."""

from __future__ import annotations

from threading import Lock

from dotenv import find_dotenv, load_dotenv

_load_lock = Lock()
_loaded = False


def ensure_env_loaded() -> None:
    """Load variables from a .env file once, without overriding existing values."""
    global _loaded
    if _loaded:
        return

    with _load_lock:
        if _loaded:
            return
        dotenv_path = find_dotenv(usecwd=True) or None
        load_dotenv(dotenv_path=dotenv_path, override=False)
        _loaded = True


__all__ = ["ensure_env_loaded"]
