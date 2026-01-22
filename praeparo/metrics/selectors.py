"""Parse and resolve `praeparo-metrics explain` selector tokens.

Selectors allow developers to target a metric key directly or drill into a specific
metric binding inside a visual/pack with one copy/paste friendly shell token.

Parsing is intentionally lightweight (string → structured token). Callers that
need richer resolution (pack slide lookup, placeholder lookup, etc.) can use the
helper resolvers in this module once they have loaded the underlying config.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence

import yaml

from praeparo.models import PackConfig, PackPlaceholder, PackSlide


@dataclass(frozen=True)
class MetricSelector:
    """Selector that targets a catalogue metric identifier."""

    metric_identifier: str


@dataclass(frozen=True)
class FileSelector:
    """File-rooted selector (<path>[#<segment>...])."""

    path: Path
    segments: tuple[str, ...] = ()


@dataclass(frozen=True)
class SlideSelector:
    """Slide selector token (either a 0-based index or an id string)."""

    raw: str
    index: int | None = None

    @classmethod
    def parse(cls, token: str) -> "SlideSelector":
        cleaned = token.strip()
        if not cleaned:
            raise ValueError("Slide selector cannot be empty.")
        if cleaned.isdigit():
            return cls(raw=cleaned, index=int(cleaned))
        return cls(raw=cleaned, index=None)


@dataclass(frozen=True)
class PlaceholderSelector:
    """Placeholder selector token (either a 0-based index or an id string)."""

    raw: str
    index: int | None = None

    @classmethod
    def parse(cls, token: str) -> "PlaceholderSelector":
        cleaned = token.strip()
        if not cleaned:
            raise ValueError("Placeholder selector cannot be empty.")
        if cleaned.isdigit():
            return cls(raw=cleaned, index=int(cleaned))
        return cls(raw=cleaned, index=None)


def parse_selector(raw: str, *, cwd: Path) -> MetricSelector | FileSelector:
    """Parse a raw selector token into a MetricSelector or FileSelector.

    Rules:
    - If the token contains '#', treat it as file-rooted (<path>#...).
    - Else, if it resolves to an existing path, treat it as file-rooted (<path>).
    - Else treat it as a catalogue metric identifier.
    """

    value = raw.strip()
    if not value:
        raise ValueError("Selector cannot be empty.")

    if "#" in value:
        path_part, *segment_parts = value.split("#")
        if not path_part.strip():
            raise ValueError("File-rooted selectors must start with a path before '#'.")
        segments = tuple(_ensure_nonempty_segments(segment_parts, label="selector segments"))
        resolved_path = _resolve_candidate_path(path_part.strip(), cwd=cwd)
        return FileSelector(path=resolved_path, segments=segments)

    candidate_path = _resolve_candidate_path(value, cwd=cwd)
    if candidate_path.exists():
        return FileSelector(path=candidate_path, segments=())

    return MetricSelector(metric_identifier=value)


def detect_selector_file_kind(path: Path) -> str:
    """Return the detected file kind: 'pack' or 'visual'."""

    payload = _load_yaml_mapping(path)
    if "slides" in payload:
        return "pack"
    if "type" in payload:
        return "visual"
    raise ValueError(f"Unsupported selector file {path}; expected a pack (slides) or visual (type).")


def resolve_pack_slide(pack: PackConfig, selector: SlideSelector) -> tuple[int, PackSlide]:
    """Resolve a PackSlide plus its 0-based index from a SlideSelector."""

    slides = list(pack.slides)
    if selector.index is not None:
        index = selector.index
        if index < 0 or index >= len(slides):
            raise ValueError(_format_unknown_slide(selector.raw, pack))
        return index, slides[index]

    slide_id = selector.raw
    for index, slide in enumerate(slides):
        if slide.id == slide_id:
            return index, slide
    raise ValueError(_format_unknown_slide(slide_id, pack))


def resolve_pack_placeholder(
    slide: PackSlide,
    selector: PlaceholderSelector,
) -> tuple[str, PackPlaceholder]:
    """Resolve a placeholder id + config from a slide."""

    placeholders = slide.placeholders
    if not placeholders:
        raise ValueError("Slide does not define placeholders.")

    ids = list(placeholders.keys())
    if selector.index is not None:
        index = selector.index
        if index < 0 or index >= len(ids):
            raise ValueError(_format_unknown_placeholder(selector.raw, ids))
        resolved_id = ids[index]
        return resolved_id, placeholders[resolved_id]

    placeholder_id = selector.raw
    if placeholder_id in placeholders:
        return placeholder_id, placeholders[placeholder_id]
    raise ValueError(_format_unknown_placeholder(placeholder_id, ids))


def _resolve_candidate_path(raw: str, *, cwd: Path) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (cwd / candidate).resolve(strict=False)


def _ensure_nonempty_segments(parts: Sequence[str], *, label: str) -> Iterable[str]:
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            raise ValueError(f"{label} cannot be empty.")
        yield cleaned


def _load_yaml_mapping(path: Path) -> Mapping[str, object]:
    resolved = path.expanduser().resolve(strict=False)
    if not resolved.exists():
        raise FileNotFoundError(f"Selector file not found: {resolved}")
    raw = resolved.read_text(encoding="utf-8")
    payload = yaml.safe_load(raw) or {}
    if not isinstance(payload, Mapping):
        raise ValueError(f"Selector file {resolved} must contain a YAML mapping at the root.")
    return dict(payload)


def _format_unknown_slide(token: str, pack: PackConfig) -> str:
    slides = list(pack.slides)
    lines = [f"Unknown slide selector '{token}'."]
    lines.append("Available slides (0-based):")
    for index, slide in enumerate(slides):
        slide_id = slide.id or "<no-id>"
        lines.append(f"  - {index}: id={slide_id} title={slide.title}")
    return "\n".join(lines)


def _format_unknown_placeholder(token: str, placeholder_ids: Sequence[str]) -> str:
    lines = [f"Unknown placeholder selector '{token}'."]
    lines.append("Available placeholders (0-based):")
    for index, placeholder_id in enumerate(placeholder_ids):
        lines.append(f"  - {index}: {placeholder_id}")
    return "\n".join(lines)


__all__ = [
    "FileSelector",
    "MetricSelector",
    "PlaceholderSelector",
    "SlideSelector",
    "detect_selector_file_kind",
    "parse_selector",
    "resolve_pack_placeholder",
    "resolve_pack_slide",
]
