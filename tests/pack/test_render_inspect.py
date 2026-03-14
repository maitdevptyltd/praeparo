from __future__ import annotations

import pytest
from pathlib import Path

from praeparo.pack.render_compare import PackRenderComparison, PackRenderComparisonEntry, RenderComparisonMetrics
from praeparo.pack.render_inspect import inspect_pack_render_target
from praeparo.pack.render_manifest import (
    PackRenderManifest,
    PackRenderManifestEntry,
    RenderManifestArtifact,
)


def test_inspect_pack_render_target_collects_related_sidecars(tmp_path: Path) -> None:
    manifest_path = tmp_path / "render.manifest.json"
    compare_path = tmp_path / "_comparisons" / "compare.manifest.json"
    compare_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = PackRenderManifest(
        kind="pack_render_slide",
        pack_path="registry/customers/foo/foo_governance_pack.yaml",
        artefact_root=".tmp/foo",
        partial_failure=True,
        warnings=["synthetic warning"],
        pack_artefacts=[
            RenderManifestArtifact(kind="dax", path=".tmp/foo/metric_context.slide_3.dax"),
            RenderManifestArtifact(kind="data", path=".tmp/foo/metric_context.slide_3.data.json"),
            RenderManifestArtifact(
                kind="file",
                path=".tmp/foo/_evidence/quarterly_performance_all_brands/top_left/row_0/evidence.csv",
            ),
            RenderManifestArtifact(
                kind="dax",
                path=".tmp/foo/_evidence/quarterly_performance_all_brands/top_left/row_0/_artifacts/explain.dax",
            ),
            RenderManifestArtifact(kind="file", path=".tmp/foo/_evidence/other_slide/row_0/evidence.csv"),
        ],
        rendered_targets=[
            PackRenderManifestEntry(
                slide_index=3,
                slide_id="quarterly_performance",
                slide_title="Quarterly Performance",
                slide_template="two_up",
                slide_slug="quarterly_performance_all_brands",
                target_slug="quarterly_performance_all_brands__top_left",
                artifact_label="[03]_quarterly_performance_all_brands__top_left",
                placeholder_id="top_left",
                visual_path="registry/customers/foo/visuals/dashboard/quarterly_top_left.yaml",
                visual_type="python",
                png_path=".tmp/foo/[03]_quarterly_performance_all_brands__top_left.png",
                artefact_dir=".tmp/foo/[03]_quarterly_performance_all_brands__top_left",
                artefacts=[
                    RenderManifestArtifact(
                        kind="png",
                        path=".tmp/foo/[03]_quarterly_performance_all_brands__top_left.png",
                    ),
                    RenderManifestArtifact(
                        kind="dax",
                        path=".tmp/foo/[03]_quarterly_performance_all_brands__top_left/python.dax",
                    ),
                    RenderManifestArtifact(
                        kind="schema",
                        path=".tmp/foo/[03]_quarterly_performance_all_brands__top_left/schema.json",
                    ),
                    RenderManifestArtifact(
                        kind="data",
                        path=".tmp/foo/[03]_quarterly_performance_all_brands__top_left/data.json",
                    ),
                ],
            )
        ],
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    comparison = PackRenderComparison(
        manifest_path=".tmp/foo/render.manifest.json",
        baseline_dir="registry/customers/foo/baselines",
        output_dir=".tmp/foo/_comparisons",
        compared_targets=1,
        matched_targets=0,
        failed_targets=1,
        comparisons=[
            PackRenderComparisonEntry(
                slide_slug="quarterly_performance_all_brands",
                target_slug="quarterly_performance_all_brands__top_left",
                status="mismatch",
                png_path=".tmp/foo/[03]_quarterly_performance_all_brands__top_left.png",
                baseline_path="registry/customers/foo/baselines/quarterly_performance_all_brands__top_left.png",
                diff_path=".tmp/foo/_comparisons/quarterly_performance_all_brands__top_left.diff.png",
                message="Rendered PNG differs from baseline.",
                metrics=RenderComparisonMetrics(
                    width=944,
                    height=388,
                    compared_pixels=366272,
                    changed_pixels=17,
                    changed_pixel_ratio=17 / 366272,
                ),
            )
        ],
    )
    compare_path.write_text(comparison.model_dump_json(indent=2) + "\n", encoding="utf-8")

    inspection = inspect_pack_render_target(
        manifest_path=manifest_path,
        selectors=("quarterly_performance_all_brands__top_left",),
        project_root=tmp_path,
    )

    assert inspection.slide_template == "two_up"
    assert inspection.visual_path == "registry/customers/foo/visuals/dashboard/quarterly_top_left.yaml"
    assert inspection.target_artifact_buckets.dax_paths == [
        ".tmp/foo/[03]_quarterly_performance_all_brands__top_left/python.dax"
    ]
    assert inspection.target_artifact_buckets.schema_paths == [
        ".tmp/foo/[03]_quarterly_performance_all_brands__top_left/schema.json"
    ]
    assert inspection.metric_context_artefacts == [
        RenderManifestArtifact(kind="dax", path=".tmp/foo/metric_context.slide_3.dax"),
        RenderManifestArtifact(kind="data", path=".tmp/foo/metric_context.slide_3.data.json"),
    ]
    assert inspection.evidence_artefacts == [
        RenderManifestArtifact(
            kind="file",
            path=".tmp/foo/_evidence/quarterly_performance_all_brands/top_left/row_0/evidence.csv",
        ),
        RenderManifestArtifact(
            kind="dax",
            path=".tmp/foo/_evidence/quarterly_performance_all_brands/top_left/row_0/_artifacts/explain.dax",
        ),
    ]
    assert inspection.comparison is not None
    assert inspection.comparison.status == "mismatch"
    assert inspection.compare_manifest_path == "_comparisons/compare.manifest.json"


def test_inspect_pack_render_target_rejects_ambiguous_selector(tmp_path: Path) -> None:
    manifest_path = tmp_path / "render.manifest.json"
    manifest = PackRenderManifest(
        kind="pack_render_slide",
        pack_path="registry/customers/foo/foo_governance_pack.yaml",
        artefact_root=".tmp/foo",
        rendered_targets=[
            PackRenderManifestEntry(
                slide_index=3,
                slide_slug="quarterly_performance_all_brands",
                target_slug="quarterly_performance_all_brands__top_left",
                artifact_label="[03]_quarterly_performance_all_brands__top_left",
            ),
            PackRenderManifestEntry(
                slide_index=3,
                slide_slug="quarterly_performance_all_brands",
                target_slug="quarterly_performance_all_brands__top_right",
                artifact_label="[03]_quarterly_performance_all_brands__top_right",
            ),
        ],
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Selectors matched multiple rendered targets"):
        inspect_pack_render_target(
            manifest_path=manifest_path,
            selectors=("quarterly_performance_all_brands",),
            project_root=tmp_path,
        )
