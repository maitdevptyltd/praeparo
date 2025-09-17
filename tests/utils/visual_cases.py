from __future__ import annotations

from pathlib import Path
from typing import Tuple

from praeparo.dax import DaxQueryPlan, build_matrix_query
from praeparo.io.yaml_loader import load_matrix_config
from praeparo.models import MatrixConfig
from praeparo.templating import FieldReference, extract_field_references


def discover_yaml_files(root: Path) -> list[Path]:
    return sorted(root.glob("**/*.yaml"))


def case_name(path: Path, root: Path) -> str:
    relative = path.relative_to(root)
    parts = list(relative.parts)
    parts[-1] = Path(parts[-1]).stem
    return "_".join(parts)


def load_visual_artifacts(path: Path) -> Tuple[MatrixConfig, tuple[FieldReference, ...], DaxQueryPlan]:
    config = load_matrix_config(path)
    row_fields = tuple(extract_field_references([row.template for row in config.rows]))
    plan = build_matrix_query(config, row_fields)
    return config, row_fields, plan
