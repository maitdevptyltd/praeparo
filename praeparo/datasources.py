"""Data source configuration utilities for Praeparo."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import TypeAdapter, ValidationError

from .models import PowerBIDataSourceConfig
from .powerbi import PowerBISettings


class DataSourceConfigError(RuntimeError):
    """Raised when a data source definition cannot be resolved."""


ENV_PATTERNS = (
    re.compile(r"^\$\{env:(?P<name>[A-Z0-9_]+)\}$"),
    re.compile(r"^env:(?P<name>[A-Z0-9_]+)$"),
)
DATASOURCE_EXTENSIONS = (".yaml", ".yml")
DATASET_ENV_KEY = "PRAEPARO_PBI_DATASET_ID"
WORKSPACE_ENV_KEY = "PRAEPARO_PBI_WORKSPACE_ID"
CLIENT_ID_ENV_KEY = "PRAEPARO_PBI_CLIENT_ID"
CLIENT_SECRET_ENV_KEY = "PRAEPARO_PBI_CLIENT_SECRET"
TENANT_ID_ENV_KEY = "PRAEPARO_PBI_TENANT_ID"
REFRESH_TOKEN_ENV_KEY = "PRAEPARO_PBI_REFRESH_TOKEN"
SCOPE_ENV_KEY = "PRAEPARO_PBI_SCOPE"
DEFAULT_SCOPE = PowerBISettings.__dataclass_fields__["scope"].default  # type: ignore[index]
DATASOURCE_ADAPTER = TypeAdapter(PowerBIDataSourceConfig)


@dataclass(frozen=True)
class ResolvedDataSource:
    """Runtime view of a data source after applying environment expansion."""

    name: str
    type: Literal["mock", "powerbi"]
    dataset_id: str | None = None
    workspace_id: str | None = None
    settings: PowerBISettings | None = None
    source_path: Path | None = None


def _expand_env_value(
    raw: str | None,
    *,
    field: str,
    source: Path,
    datasource: str,
) -> str | None:
    if raw is None:
        return None

    text = raw.strip()
    if not text:
        return None

    for pattern in ENV_PATTERNS:
        match = pattern.match(text)
        if match:
            env_name = match.group("name")
            resolved = os.getenv(env_name)
            if resolved is None:
                msg = (
                    f"Environment variable '{env_name}' required by data source '{datasource}'"
                    f" is not set ({source})."
                )
                raise DataSourceConfigError(msg)
            return resolved

    return text


def _ancestor_directories(start: Path) -> list[Path]:
    current = start
    ancestors: list[Path] = [current]
    while current.parent != current:
        current = current.parent
        ancestors.append(current)
    return ancestors


def _candidate_paths(reference: str, visual_path: Path) -> list[Path]:
    ref_path = Path(reference)
    ancestors = _ancestor_directories(visual_path.parent)
    candidates: list[Path] = []
    seen: set[Path] = set()

    def _register(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    if ref_path.suffix in DATASOURCE_EXTENSIONS or ref_path.name != reference:
        if ref_path.is_absolute():
            _register(ref_path)
        else:
            for base in ancestors:
                _register(base / ref_path)
        return candidates

    for base in ancestors:
        data_dir = base / "datasources"
        if data_dir.is_dir():
            for ext in DATASOURCE_EXTENSIONS:
                _register(data_dir / f"{reference}{ext}")
        for ext in DATASOURCE_EXTENSIONS:
            _register(base / f"{reference}{ext}")

    return candidates


def _load_raw_yaml(path: Path) -> dict:
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Failed to read data source definition: {path}"
        raise DataSourceConfigError(msg) from exc
    try:
        payload = yaml.safe_load(contents) or {}
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML syntax in data source: {path}"
        raise DataSourceConfigError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"Expected mapping at data source root: {path}"
        raise DataSourceConfigError(msg)
    return payload


def load_datasource_config(path: Path) -> PowerBIDataSourceConfig:
    payload = _load_raw_yaml(path)
    try:
        return DATASOURCE_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        msg = f"Data source configuration validation failed for {path}"
        raise DataSourceConfigError(msg) from exc


def _resolve_field(
    value: str | None,
    *,
    field: str,
    source: Path,
    datasource: str,
    env_key: str | None,
    required: bool,
    default: str | None = None,
) -> str | None:
    resolved = _expand_env_value(
        value, field=field, source=source, datasource=datasource
    )
    if resolved is None and env_key:
        resolved = os.getenv(env_key)
    if resolved is None:
        if required:
            target = env_key if env_key else field
            msg = (
                f"Data source '{datasource}' missing required field '{field}' ({source})."
                f" Set it explicitly or provide environment variable '{target}'."
            )
            raise DataSourceConfigError(msg)
        return default
    return resolved


def _resolve_powerbi_settings(
    config: PowerBIDataSourceConfig,
    *,
    source: Path,
    datasource: str,
) -> PowerBISettings:
    tenant_id = _resolve_field(
        config.tenant_id,
        field="tenant_id",
        source=source,
        datasource=datasource,
        env_key=TENANT_ID_ENV_KEY,
        required=True,
    )
    client_id = _resolve_field(
        config.client_id,
        field="client_id",
        source=source,
        datasource=datasource,
        env_key=CLIENT_ID_ENV_KEY,
        required=True,
    )
    client_secret = _resolve_field(
        config.client_secret,
        field="client_secret",
        source=source,
        datasource=datasource,
        env_key=CLIENT_SECRET_ENV_KEY,
        required=True,
    )
    refresh_token = _resolve_field(
        config.refresh_token,
        field="refresh_token",
        source=source,
        datasource=datasource,
        env_key=REFRESH_TOKEN_ENV_KEY,
        required=True,
    )
    scope = (
        _resolve_field(
            config.scope,
            field="scope",
            source=source,
            datasource=datasource,
            env_key=SCOPE_ENV_KEY,
            required=False,
            default=DEFAULT_SCOPE,
        )
        or DEFAULT_SCOPE
    )

    return PowerBISettings(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        scope=scope,
    )


def resolve_datasource(
    reference: str | None,
    *,
    visual_path: Path,
) -> ResolvedDataSource:
    if reference is None:
        return ResolvedDataSource(name="mock", type="mock")

    normalized = reference.strip()
    if not normalized:
        return ResolvedDataSource(name="mock", type="mock")

    candidates = _candidate_paths(normalized, visual_path)
    target: Path | None = None
    for candidate in candidates:
        if candidate.exists():
            target = candidate
            break

    if target is None:
        if normalized.lower() == "mock":
            return ResolvedDataSource(name="mock", type="mock")
        if candidates:
            msg = f"Data source definition not found: {candidates[0]}"
        else:
            msg = (
                f"Unable to locate data source '{normalized}' for visual {visual_path}."
                " Provide a name (searched under datasources/) or a YAML path."
            )
        raise DataSourceConfigError(msg)

    config = load_datasource_config(target)
    dataset_id = _resolve_field(
        config.dataset_id,
        field="dataset_id",
        source=target,
        datasource=normalized,
        env_key=DATASET_ENV_KEY,
        required=True,
    )
    workspace_id = _resolve_field(
        config.workspace_id,
        field="workspace_id",
        source=target,
        datasource=normalized,
        env_key=WORKSPACE_ENV_KEY,
        required=False,
    )
    settings = _resolve_powerbi_settings(config, source=target, datasource=normalized)

    name = normalized or target.stem
    return ResolvedDataSource(
        name=name,
        type="powerbi",
        dataset_id=dataset_id,
        workspace_id=workspace_id,
        settings=settings,
        source_path=target,
    )


__all__ = [
    "DataSourceConfigError",
    "ResolvedDataSource",
    "load_datasource_config",
    "resolve_datasource",
]
