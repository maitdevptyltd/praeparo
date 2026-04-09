from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from praeparo.cli import _instantiate_visual_context
from praeparo.pack.runner import _instantiate_slide_context
from praeparo.visuals.context_models import VisualContextModel
from praeparo.visuals.registry import VisualTypeRegistration


def _dummy_registration() -> VisualTypeRegistration:
    return VisualTypeRegistration(
        loader=lambda *_, **__: None,
        cli=None,
        context_model=VisualContextModel,
    )


def test_pack_context_defaults_metrics_root_to_cwd(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    registration = _dummy_registration()

    context = _instantiate_slide_context(
        registration=registration,
        metadata={},
        project_root=tmp_path / "customers" / "example_customer",
    )

    assert context is not None
    assert context.metrics_root == (tmp_path / "registry" / "metrics").resolve()


def test_visual_context_defaults_metrics_root_to_cwd(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    registration = _dummy_registration()

    args = Namespace(metrics_root=None, grain=None, calculate=None, define=None)
    metadata: dict[str, object] = {}
    project_root = tmp_path / "customers" / "example_customer"

    context = _instantiate_visual_context(
        args=args,
        registration=registration,
        metadata=metadata,
        project_root=project_root,
    )

    assert context is not None
    assert context.metrics_root == (tmp_path / "registry" / "metrics").resolve()
