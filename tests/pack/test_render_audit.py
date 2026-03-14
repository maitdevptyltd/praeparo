from __future__ import annotations

from pathlib import Path

from PIL import Image

from praeparo.pack.render_audit import audit_pack_render_manifest
from praeparo.pack.render_manifest import PackRenderManifest, PackRenderManifestEntry


def test_audit_pack_render_manifest_summarizes_failures_and_emits_inspections(tmp_path: Path) -> None:
    project_root = tmp_path
    render_dir = project_root / "renders"
    baseline_dir = project_root / "baselines"

    match_png = render_dir / "slide-id-1.png"
    mismatch_png = render_dir / "slide-id-2.png"
    _write_png(match_png, colour=(10, 20, 30, 255))
    _write_png(mismatch_png, colour=(255, 0, 0, 255))
    _write_png(baseline_dir / "slide-id-1.png", colour=(10, 20, 30, 255))
    _write_png(baseline_dir / "slide-id-2.png", colour=(0, 0, 255, 255))

    manifest_path = project_root / "render.manifest.json"
    manifest = PackRenderManifest(
        kind="pack_render_slide",
        pack_path="registry/customers/test/pack.yaml",
        artefact_root="renders",
        warnings=["synthetic warning"],
        rendered_targets=[
            PackRenderManifestEntry(
                slide_index=1,
                slide_id="slide_id_1",
                slide_title="Slide One",
                slide_template="full_page_image",
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                visual_path="registry/customers/test/visuals/slide_1.yaml",
                visual_type="governance_matrix",
                png_path="renders/slide-id-1.png",
            ),
            PackRenderManifestEntry(
                slide_index=2,
                slide_id="slide_id_2",
                slide_title="Slide Two",
                slide_template="full_page_image",
                slide_slug="slide-id-2",
                target_slug="slide-id-2",
                artifact_label="[02]_slide-id-2",
                visual_path="registry/customers/test/visuals/slide_2.yaml",
                visual_type="governance_matrix",
                png_path="renders/slide-id-2.png",
            ),
        ],
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    audit = audit_pack_render_manifest(
        manifest_path=manifest_path,
        baseline_dir=baseline_dir,
        project_root=project_root,
    )

    assert audit.audited_targets == 2
    assert audit.matched_targets == 1
    assert audit.attention_targets == 1
    assert audit.mismatched_targets == 1
    assert audit.inspections_generated == 1
    assert audit.compare_manifest_path == "_comparisons/compare.manifest.json"
    assert audit.targets[0].status == "match"
    assert audit.targets[1].status == "mismatch"
    assert audit.targets[1].inspection_path == "_inspections/slide-id-2.inspect.json"
    assert (project_root / "_comparisons" / "compare.manifest.json").exists()
    assert (project_root / "_inspections" / "slide-id-2.inspect.json").exists()


def test_audit_pack_render_manifest_without_compare_marks_targets_unchecked(tmp_path: Path) -> None:
    manifest_path = tmp_path / "render.manifest.json"
    manifest = PackRenderManifest(
        kind="pack_render_slide",
        pack_path="registry/customers/test/pack.yaml",
        artefact_root="renders",
        rendered_targets=[
            PackRenderManifestEntry(
                slide_index=1,
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                png_path="renders/slide-id-1.png",
            )
        ],
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    audit = audit_pack_render_manifest(
        manifest_path=manifest_path,
        project_root=tmp_path,
        emit_inspections=False,
    )

    assert audit.audited_targets == 1
    assert audit.unchecked_targets == 1
    assert audit.attention_targets == 0
    assert audit.targets[0].status == "unchecked"
    assert audit.targets[0].inspection_path is None


def _write_png(path: Path, *, colour: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (24, 16), color=colour)
    image.save(path)
