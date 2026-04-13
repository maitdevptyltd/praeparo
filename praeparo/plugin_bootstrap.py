"""Shared plugin discovery for Praeparo CLI entrypoints.

This bootstrap runs before the main CLI parser is built so downstream plugins
can register visuals, bindings, and schema branches in time for every Praeparo
entrypoint. The discovery path is intentionally layered: explicit `--plugin`
flags win, then environment configuration, then a workspace manifest, and
finally a narrow opt-in convention scan for known package layouts.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

PLUGIN_ENV_VAR = "PRAEPARO_PLUGINS"
_MANIFEST_FILENAMES = ("praeparo.yaml", "praeparo.yml")
_PYPROJECT_FILENAME = "pyproject.toml"


@dataclass(frozen=True)
class PluginCandidate:
    """Resolved plugin module plus the path needed to import it."""

    module: str
    source: str
    import_root: Path


def _normalise_modules(raw_modules: Iterable[object], *, source: str, import_root: Path) -> list[PluginCandidate]:
    modules: list[PluginCandidate] = []
    for raw_module in raw_modules:
        if not isinstance(raw_module, str):
            msg = f"{source} plugins must be declared as module strings."
            raise ValueError(msg)
        module = raw_module.strip()
        if module:
            modules.append(PluginCandidate(module=module, source=source, import_root=import_root))
    return modules


def _dedupe_candidates(candidates: Iterable[PluginCandidate]) -> list[PluginCandidate]:
    deduped: list[PluginCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.module in seen:
            continue
        deduped.append(candidate)
        seen.add(candidate.module)
    return deduped


def parse_explicit_plugins(argv: Sequence[str]) -> list[str]:
    """Return modules supplied explicitly via repeatable ``--plugin`` flags."""

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plugin", dest="plugins", action="append", default=[])
    args, _ = parser.parse_known_args(list(argv))
    return [module.strip() for module in args.plugins if isinstance(module, str) and module.strip()]


def _parse_project_root_hint(argv: Sequence[str]) -> Path | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", dest="project_root", type=Path, default=None)
    args, _ = parser.parse_known_args(list(argv))
    return args.project_root


def _iter_ancestor_roots(start: Path) -> Iterable[Path]:
    current = start
    yield current
    yield from current.parents


def find_project_root(argv: Sequence[str], cwd: Path | None = None) -> Path:
    """Resolve the workspace root used for manifest and convention discovery.

    We prefer an explicit `--project-root` when the caller supplies one. Beyond
    that, the nearest `praeparo.yaml` is the clearest signal that a directory is
    meant to behave like a Praeparo workspace, with `pyproject.toml` kept as a
    weaker fallback for package-root detection.
    """

    root_hint = _parse_project_root_hint(argv)
    if root_hint is not None:
        return root_hint.expanduser().resolve(strict=False)

    search_from = (cwd or Path.cwd()).expanduser().resolve(strict=False)
    manifest_match: Path | None = None
    pyproject_match: Path | None = None

    # Walk upward once and remember the first manifest/package root we see so
    # plugin discovery, manifest loading, and import-root resolution all share
    # the same workspace anchor.
    for candidate in _iter_ancestor_roots(search_from):
        if manifest_match is None and any((candidate / name).is_file() for name in _MANIFEST_FILENAMES):
            manifest_match = candidate
        if pyproject_match is None and (candidate / _PYPROJECT_FILENAME).is_file():
            pyproject_match = candidate
        if manifest_match is not None and pyproject_match is not None:
            break

    return manifest_match or pyproject_match or search_from


def load_env_plugins(*, cwd: Path | None = None) -> list[PluginCandidate]:
    """Return modules declared in ``PRAEPARO_PLUGINS``."""

    raw = os.getenv(PLUGIN_ENV_VAR, "")
    if not raw.strip():
        return []

    split_pattern = re.compile(rf"[,\n\r{re.escape(os.pathsep)}]+")
    modules = [item.strip() for item in split_pattern.split(raw) if item.strip()]
    import_root = (cwd or Path.cwd()).expanduser().resolve(strict=False)
    return _normalise_modules(modules, source=PLUGIN_ENV_VAR, import_root=import_root)


def _read_yaml_document(path: Path) -> Mapping[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        msg = f"Failed to read plugin manifest: {path}"
        raise RuntimeError(msg) from exc
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in plugin manifest: {path}"
        raise RuntimeError(msg) from exc

    if not isinstance(payload, Mapping):
        msg = f"Plugin manifest must define a mapping at the document root: {path}"
        raise RuntimeError(msg)
    return payload


def load_manifest_plugins(project_root: Path) -> list[PluginCandidate]:
    """Return modules declared in the nearest ``praeparo.yaml`` manifest."""

    # The workspace manifest is intentionally narrow: one root file, one
    # `plugins` key, and the first matching filename wins. That keeps the
    # shared discovery contract stable across hosts and editors.
    for manifest_name in _MANIFEST_FILENAMES:
        manifest_path = project_root / manifest_name
        if not manifest_path.is_file():
            continue
        payload = _read_yaml_document(manifest_path)
        raw_plugins = payload.get("plugins") or []
        if not isinstance(raw_plugins, list):
            msg = f"'plugins' must be a list in {manifest_path}"
            raise RuntimeError(msg)
        return _normalise_modules(raw_plugins, source=str(manifest_path.relative_to(project_root)), import_root=project_root)
    return []


def _read_pyproject(path: Path) -> Mapping[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"Failed to read pyproject metadata: {path}"
        raise RuntimeError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"Invalid TOML in {path}"
        raise RuntimeError(msg) from exc


def _load_pyproject_plugin_candidates(path: Path) -> list[PluginCandidate]:
    # Convention scanning is opt-in. A package only participates when it
    # declares Praeparo plugin metadata in its own pyproject, and that metadata
    # also tells us which path should be added to sys.path before import.
    payload = _read_pyproject(path)
    tool = payload.get("tool")
    if not isinstance(tool, Mapping):
        return []
    praeparo = tool.get("praeparo")
    if not isinstance(praeparo, Mapping):
        return []

    raw_modules: object = praeparo.get("plugins")
    if raw_modules is None:
        raw_module = praeparo.get("plugin")
        if raw_module is not None:
            raw_modules = [raw_module]
    if raw_modules is None:
        return []
    if not isinstance(raw_modules, list):
        msg = f"[tool.praeparo].plugins must be a list in {path}"
        raise RuntimeError(msg)

    raw_import_root = praeparo.get("import_root", praeparo.get("import-root", "."))
    if not isinstance(raw_import_root, str):
        msg = f"[tool.praeparo].import_root must be a string in {path}"
        raise RuntimeError(msg)
    import_root = (path.parent / raw_import_root).expanduser().resolve(strict=False)
    return _normalise_modules(raw_modules, source=str(path), import_root=import_root)


def discover_convention_plugins(project_root: Path) -> list[PluginCandidate]:
    """Return opt-in plugin declarations from the current and future package layouts."""

    candidates: list[PluginCandidate] = []
    root_pyproject = project_root / _PYPROJECT_FILENAME
    if root_pyproject.is_file():
        candidates.extend(_load_pyproject_plugin_candidates(root_pyproject))

    # Support the current root-package layout plus a future `packages/*` layout
    # without treating every sibling package as a Praeparo plugin.
    packages_dir = project_root / "packages"
    if packages_dir.is_dir():
        for package_dir in sorted(item for item in packages_dir.iterdir() if item.is_dir()):
            package_pyproject = package_dir / _PYPROJECT_FILENAME
            if package_pyproject.is_file():
                candidates.extend(_load_pyproject_plugin_candidates(package_pyproject))

    return candidates


def discover_plugin_candidates(argv: Sequence[str], cwd: Path | None = None) -> list[PluginCandidate]:
    """Resolve plugins from explicit flags, env, manifest, and convention metadata."""

    project_root = find_project_root(argv, cwd=cwd)
    # Earlier sources win. We preserve first-seen order through de-duplication
    # so an explicit flag can override the same module being declared elsewhere.
    explicit = _normalise_modules(
        parse_explicit_plugins(argv),
        source="--plugin",
        import_root=project_root,
    )
    candidates = [
        *explicit,
        *load_env_plugins(cwd=project_root),
        *load_manifest_plugins(project_root),
        *discover_convention_plugins(project_root),
    ]
    return _dedupe_candidates(candidates)


def bootstrap_plugins(argv: Sequence[str], cwd: Path | None = None) -> list[str]:
    """Import every plugin discovered for the active CLI invocation."""

    loaded: list[str] = []
    # Import side effects are the point here: plugin modules register visuals,
    # bindings, and schema branches before the CLI snapshots those registries.
    for candidate in discover_plugin_candidates(argv, cwd=cwd):
        import_root = str(candidate.import_root)
        if import_root not in sys.path:
            sys.path.insert(0, import_root)
        importlib.import_module(candidate.module)
        loaded.append(candidate.module)
    return loaded


__all__ = [
    "PLUGIN_ENV_VAR",
    "PluginCandidate",
    "bootstrap_plugins",
    "discover_convention_plugins",
    "discover_plugin_candidates",
    "find_project_root",
    "load_env_plugins",
    "load_manifest_plugins",
    "parse_explicit_plugins",
]
