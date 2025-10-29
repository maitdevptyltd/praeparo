from __future__ import annotations

import os

from praeparo import env as praeparo_env


def _reset_loader() -> None:
    praeparo_env._loaded = False  # type: ignore[attr-defined]


def test_ensure_env_loaded_walks_parent_directories(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    nested = project_root / "nested" / "child"
    nested.mkdir(parents=True)

    env_path = project_root / ".env"
    env_path.write_text("PRAEPARO_TEST_CLIENT_ID=from-dotenv\n", encoding="utf-8")

    monkeypatch.chdir(nested)
    monkeypatch.delenv("PRAEPARO_TEST_CLIENT_ID", raising=False)

    _reset_loader()
    praeparo_env.ensure_env_loaded()

    assert os.environ["PRAEPARO_TEST_CLIENT_ID"] == "from-dotenv"


def test_ensure_env_loaded_preserves_existing_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("PRAEPARO_TEST_CLIENT_SECRET=from-dotenv\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PRAEPARO_TEST_CLIENT_SECRET", "pre-set")

    _reset_loader()
    praeparo_env.ensure_env_loaded()

    assert os.environ["PRAEPARO_TEST_CLIENT_SECRET"] == "pre-set"
