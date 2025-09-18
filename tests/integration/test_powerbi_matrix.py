import asyncio
import os
from pathlib import Path
from typing import Iterable

import pytest

from praeparo.data import mock_matrix_data, powerbi_matrix_data
from tests.utils.matrix_cases import MatrixDataProviderRegistry, run_matrix_case
from tests.utils.visual_cases import MatrixArtifacts, case_name, case_snapshot_path, discover_yaml_files, load_visual_artifacts

DATASET_ENV_KEY = "PRAEPARO_PBI_DATASET_ID"
WORKSPACE_ENV_KEY = "PRAEPARO_PBI_WORKSPACE_ID"
REQUIRED_ENV = (
    "PRAEPARO_PBI_CLIENT_ID",
    "PRAEPARO_PBI_CLIENT_SECRET",
    "PRAEPARO_PBI_TENANT_ID",
    "PRAEPARO_PBI_REFRESH_TOKEN",
    DATASET_ENV_KEY,
)
INTEGRATION_ROOT = Path("tests/integration")
EXAMPLE_ROOT = Path("examples")
CAPTURE_PNG = os.getenv("PRAEPARO_PBI_CAPTURE_PNG", "1") == "1"


def _ensure_env() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing Power BI environment variables: {', '.join(missing)}")
    return {name: os.getenv(name, "") for name in REQUIRED_ENV}


def _mock_matrix_provider(config, row_fields, plan):
    return mock_matrix_data(config, row_fields)


def _powerbi_matrix_provider(config, row_fields, plan):
    env_values = _ensure_env()
    dataset_id = env_values[DATASET_ENV_KEY]
    workspace_id = os.getenv(WORKSPACE_ENV_KEY)
    if not workspace_id:
        pytest.skip(f"Missing Power BI environment variable: {WORKSPACE_ENV_KEY}")
    return asyncio.run(
        powerbi_matrix_data(
            config,
            row_fields,
            plan,
            dataset_id=dataset_id,
            group_id=workspace_id,
        )
    )


def _provider_for(key: str):
    key = key.strip().lower()
    if key == "mock":
        return _mock_matrix_provider
    if key == "powerbi":
        return _powerbi_matrix_provider
    raise ValueError(f"Unsupported matrix data provider '{key}'")


def _parse_provider_overrides(raw: str) -> dict[str, str]:
    overrides: dict[str, str] = {}
    if not raw:
        return overrides
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        case_key, provider_key = (part.strip() for part in entry.split("=", 1))
        if case_key:
            overrides[case_key] = provider_key.strip()
    return overrides


def _build_provider_registry() -> MatrixDataProviderRegistry:
    default_key = os.getenv("PRAEPARO_MATRIX_PROVIDER", "powerbi")
    default_provider = _provider_for(default_key)
    overrides_raw = os.getenv("PRAEPARO_MATRIX_PROVIDER_CASES", "")
    overrides = {
        case: _provider_for(provider_key)
        for case, provider_key in _parse_provider_overrides(overrides_raw).items()
    }
    return MatrixDataProviderRegistry(default=default_provider, overrides=overrides)


def _discover_example_visuals(root: Path) -> Iterable[tuple[Path, Path]]:
    if not root.is_dir():
        return []
    cases: list[tuple[Path, Path]] = []
    for project in root.iterdir():
        visuals_dir = project / "visuals"
        if visuals_dir.is_dir():
            for path in discover_yaml_files(visuals_dir):
                cases.append((visuals_dir, path))
    return cases


def _discover_integration_cases() -> list[tuple[Path, Path]]:
    cases: list[tuple[Path, Path]] = []
    if INTEGRATION_ROOT.is_dir():
        for path in discover_yaml_files(INTEGRATION_ROOT):
            cases.append((INTEGRATION_ROOT, path))
    cases.extend(_discover_example_visuals(EXAMPLE_ROOT))
    return cases


DATA_PROVIDERS = _build_provider_registry()
INTEGRATION_CASES = _discover_integration_cases()
INTEGRATION_IDS = [case_name(path, root) for root, path in INTEGRATION_CASES]

if not INTEGRATION_CASES:
    pytestmark = pytest.mark.skip(reason="No integration visuals discovered")


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("PRAEPARO_RUN_POWERBI_TESTS") != "1",
    reason="Set PRAEPARO_RUN_POWERBI_TESTS=1 to enable live Power BI integration tests.",
)
@pytest.mark.parametrize(
    ("case_root", "yaml_path"),
    INTEGRATION_CASES,
    ids=INTEGRATION_IDS or None,
)
def test_powerbi_matrix_snapshot(snapshot, case_root: Path, yaml_path: Path) -> None:
    case = case_name(yaml_path, case_root)
    snapshot_path = case_snapshot_path(yaml_path, case_root)
    artifacts = load_visual_artifacts(yaml_path)
    assert isinstance(artifacts, MatrixArtifacts), "Integration visuals must be matrix configs"

    provider = DATA_PROVIDERS.resolve(case)

    run_matrix_case(
        snapshot,
        case,
        artifacts,
        data_provider=provider,
        snapshot_path=snapshot_path,
        capture_png=CAPTURE_PNG,
        png_requires_kaleido=False,
        ensure_non_empty_rows=True,
        ensure_values_present=True,
        validate_define=True,
        sort_rows=True,
        visual_path=yaml_path,
    )
