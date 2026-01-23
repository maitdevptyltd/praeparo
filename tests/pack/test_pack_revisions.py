from __future__ import annotations

import json
from pathlib import Path

from praeparo.pack.revisions import allocate_revision


def test_allocate_revision_override(tmp_path: Path) -> None:
    artefact_root = tmp_path / "_artifacts"
    artefact_root.mkdir()
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    info = allocate_revision(
        pack_path,
        artefact_root=artefact_root,
        pack_context={},
        strategy=None,
        override="2025-12",
    )

    assert info is not None
    assert info.revision == "2025-12"
    assert info.pptx_name.endswith("_2025-12.pptx")


def test_allocate_revision_full_and_minor_manifest(tmp_path: Path) -> None:
    artefact_root = tmp_path / "dest" / "_artifacts"
    artefact_root.mkdir(parents=True)
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    info_full = allocate_revision(
        pack_path,
        artefact_root=artefact_root,
        pack_context={"month": "2025-12-01"},
        strategy="full",
        override=None,
    )
    manifest_path = artefact_root.parent / "_revisions" / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["revision"] == "2025-12"
    assert manifest["minor"] == 1
    assert info_full.pptx_name.endswith("_2025-12.pptx")

    info_minor = allocate_revision(
        pack_path,
        artefact_root=artefact_root,
        pack_context={"month": "2025-12-01"},
        strategy="minor",
        override=None,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["minor"] == 2
    assert info_minor.minor == 2
    assert info_minor.revision == "2025-12"
    assert info_minor.pptx_name.endswith("_2025-12_r02.pptx")


def test_allocate_revision_full_without_month_uses_padded_r_token(tmp_path: Path) -> None:
    artefact_root = tmp_path / "dest" / "_artifacts"
    artefact_root.mkdir(parents=True)
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    info_first = allocate_revision(
        pack_path,
        artefact_root=artefact_root,
        pack_context={},
        strategy="full",
        override=None,
    )
    assert info_first is not None
    assert info_first.revision == "r01"
    assert info_first.pptx_name.endswith("_r01.pptx")

    info_second = allocate_revision(
        pack_path,
        artefact_root=artefact_root,
        pack_context={},
        strategy="full",
        override=None,
    )
    assert info_second is not None
    assert info_second.revision == "r02"
    assert info_second.pptx_name.endswith("_r02.pptx")


def test_allocate_revision_minor_without_month_uses_padded_minor_suffix(tmp_path: Path) -> None:
    artefact_root = tmp_path / "dest" / "_artifacts"
    artefact_root.mkdir(parents=True)
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    info_full = allocate_revision(
        pack_path,
        artefact_root=artefact_root,
        pack_context={},
        strategy="full",
        override=None,
    )
    assert info_full is not None
    assert info_full.revision == "r01"
    assert info_full.minor == 1
    assert info_full.pptx_name.endswith("_r01.pptx")

    info_minor = allocate_revision(
        pack_path,
        artefact_root=artefact_root,
        pack_context={},
        strategy="minor",
        override=None,
    )
    assert info_minor is not None
    assert info_minor.revision == "r01"
    assert info_minor.minor == 2
    assert info_minor.pptx_name.endswith("_r01_r02.pptx")


def test_allocate_revision_dry_run_skips_manifest(tmp_path: Path) -> None:
    artefact_root = tmp_path / "_artifacts"
    artefact_root.mkdir()
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    info = allocate_revision(
        pack_path,
        artefact_root=artefact_root,
        pack_context={"month": "2025-11-01"},
        strategy="full",
        override=None,
        dry_run=True,
    )

    assert info is not None
    manifest_path = artefact_root.parent / "_revisions" / "manifest.json"
    assert not manifest_path.exists()
