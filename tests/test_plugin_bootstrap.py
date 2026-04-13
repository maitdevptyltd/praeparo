from __future__ import annotations

import builtins
from pathlib import Path

from praeparo.plugin_bootstrap import bootstrap_plugins, discover_plugin_candidates


def test_discover_plugin_candidates_honours_precedence_and_deduplicates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "praeparo.yaml").write_text("plugins:\n  - manifest_plugin\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.praeparo]\nplugins = [\"manifest_plugin\", \"root_plugin\"]\n",
        encoding="utf-8",
    )

    package_root = tmp_path / "packages" / "sample_plugin"
    package_root.mkdir(parents=True)
    (package_root / "pyproject.toml").write_text(
        "[tool.praeparo]\nplugin = \"package_plugin\"\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("PRAEPARO_PLUGINS", "env_plugin,manifest_plugin")
    candidates = discover_plugin_candidates(
        ["--plugin", "explicit_plugin", "--plugin", "env_plugin"],
        cwd=tmp_path,
    )

    assert [candidate.module for candidate in candidates] == [
        "explicit_plugin",
        "env_plugin",
        "manifest_plugin",
        "root_plugin",
        "package_plugin",
    ]


def test_bootstrap_plugins_reads_manifest_modules(tmp_path: Path, monkeypatch) -> None:
    plugin_module = tmp_path / "manifest_plugin.py"
    plugin_module.write_text(
        "import builtins\nbuiltins.__praeparo_manifest_plugin_loaded__ = True\n",
        encoding="utf-8",
    )
    (tmp_path / "praeparo.yaml").write_text("plugins:\n  - manifest_plugin\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    try:
        bootstrap_plugins([], cwd=tmp_path)
        assert getattr(builtins, "__praeparo_manifest_plugin_loaded__", False) is True
    finally:
        if hasattr(builtins, "__praeparo_manifest_plugin_loaded__"):
            delattr(builtins, "__praeparo_manifest_plugin_loaded__")
