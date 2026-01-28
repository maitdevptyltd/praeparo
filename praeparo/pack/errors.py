"""Pack-specific exceptions used to surface actionable debugging context."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence


def _first_line(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    return cleaned.splitlines()[0].strip()


def _format_dax_hint(paths: Sequence[Path]) -> str | None:
    if not paths:
        return None
    if len(paths) == 1:
        return str(paths[0])
    return f"{paths[0]} (+{len(paths) - 1} more)"


class PackExecutionError(Exception):
    """Wrap a slide failure with pack + slide + visual context.

    Pack runs often fan out across multiple phases (visual resolution, loading,
    pipeline execution, Power BI export). When a failure bubbles out without
    context it's difficult to pinpoint which slide/visual caused the issue.

    This error keeps the original exception as the cause while presenting a
    single-line, scan-friendly message that identifies the pack, slide, phase,
    and any known DAX artifact paths.
    """

    def __init__(
        self,
        *,
        pack_path: Path,
        phase: str,
        slide_index: int | None = None,
        slide_slug: str | None = None,
        slide_id: str | None = None,
        slide_title: str | None = None,
        visual_ref: str | None = None,
        visual_path: Path | None = None,
        dax_artifact_paths: Iterable[Path] = (),
        cause: BaseException | None = None,
    ) -> None:
        self.pack_path = pack_path
        self.phase = phase
        self.slide_index = slide_index
        self.slide_slug = slide_slug
        self.slide_id = slide_id
        self.slide_title = slide_title
        self.visual_ref = visual_ref
        self.visual_path = visual_path
        self.dax_artifact_paths = tuple(Path(path) for path in dax_artifact_paths)

        cause_type = cause.__class__.__name__ if cause else "Error"
        cause_message = _first_line(str(cause)) if cause else ""

        slide_label = slide_slug or "<unknown>"
        title_suffix = f" ({slide_title})" if slide_title else ""

        slide_bits: list[str] = [f"slide {slide_label}{title_suffix}"]
        if slide_index is not None:
            slide_bits.append(f"index={slide_index}")
        if slide_id:
            slide_bits.append(f"id={slide_id}")

        if visual_ref:
            slide_bits.append(f"visual_ref={visual_ref}")
        if visual_path is not None:
            slide_bits.append(f"visual_path={visual_path}")

        details = " ".join(slide_bits)

        dax_hint = _format_dax_hint(self.dax_artifact_paths)
        dax_suffix = f"; see DAX: {dax_hint}" if dax_hint else ""

        message = f"Pack {pack_path} {details} phase={phase}: {cause_type}: {cause_message}{dax_suffix}".rstrip()
        super().__init__(message)

        if cause is not None:
            # When we construct wrapper errors outside a `raise ... from ...` block
            # (for example, Power BI queue summaries), set the cause explicitly so
            # downstream tooling can still surface the root exception.
            self.__cause__ = cause


class PackEvidenceFailure(RuntimeError):
    """Raised when post-run evidence exports fail under on_error=fail.

    This mirrors the Power BI failure ergonomics by carrying successful results so
    callers (CLI, automation) can keep any slide artefacts already produced while
    still surfacing a non-zero exit.
    """

    def __init__(
        self,
        *,
        pack_path: Path,
        manifest_path: Path,
        failure_count: int,
        successful_results: Sequence[object] = (),
    ) -> None:
        self.pack_path = pack_path
        self.manifest_path = manifest_path
        self.failure_count = int(failure_count)
        self.successful_results = list(successful_results)

        plural = "s" if self.failure_count != 1 else ""
        super().__init__(
            f"Pack {pack_path} evidence export failure{plural}: {self.failure_count} binding{plural} failed; "
            f"see manifest: {manifest_path}"
        )


__all__ = ["PackExecutionError", "PackEvidenceFailure"]
