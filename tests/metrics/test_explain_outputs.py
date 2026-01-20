from __future__ import annotations

from pathlib import Path

from praeparo.metrics.explain_runner import derive_explain_outputs


def test_derive_explain_outputs_defaults_to_tmp() -> None:
    outputs = derive_explain_outputs(metric_identifier="documents_verified.within_1_day", dest=None)
    assert outputs.evidence_path.name == "evidence.csv"
    assert outputs.artefact_dir.name == "_artifacts"
    assert outputs.dax_path.name == "explain.dax"
    assert outputs.summary_path.name == "summary.json"


def test_derive_explain_outputs_file_dest_creates_sibling_artifacts(tmp_path: Path) -> None:
    dest = tmp_path / "out.csv"
    outputs = derive_explain_outputs(metric_identifier="documents_verified", dest=dest)
    assert outputs.evidence_path == dest
    assert outputs.artefact_dir == tmp_path / "out" / "_artifacts"


def test_derive_explain_outputs_directory_dest_writes_evidence_csv(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    outputs = derive_explain_outputs(metric_identifier="documents_verified", dest=dest)
    assert outputs.evidence_path == dest / "evidence.csv"
    assert outputs.artefact_dir == dest / "_artifacts"
