"""Loader utilities for pack configurations."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Mapping, Any

import yaml
from pydantic import ValidationError

from praeparo.models import PackConfig
from praeparo.paths.registry_root import is_registry_anchored_path


class PackConfigError(ValueError):
    """Raised when a pack configuration cannot be loaded or validated."""


PackLoadStack = tuple[Path, ...]
_SLIDE_SOURCE_ROOT_KEY = "__praeparo_slide_source_root"


def _annotate_slide_source_roots(slides: list[dict[str, Any]], *, source_root: Path) -> None:
    """Stamp each slide mapping with the directory that declared it."""

    root_value = str(source_root)
    for slide in slides:
        slide[_SLIDE_SOURCE_ROOT_KEY] = root_value


def _parse_slide_source_roots(payload: Mapping[str, Any]) -> list[Path | None]:
    """Extract slide declaration roots from a composed payload."""

    raw_slides = payload.get("slides")
    if not isinstance(raw_slides, list):
        return []

    parsed: list[Path | None] = []
    for slide in raw_slides:
        if not isinstance(slide, Mapping):
            parsed.append(None)
            continue
        raw_root = slide.get(_SLIDE_SOURCE_ROOT_KEY)
        if isinstance(raw_root, str) and raw_root.strip():
            parsed.append(Path(raw_root).expanduser().resolve(strict=False))
        else:
            parsed.append(None)
    return parsed


def _strip_internal_slide_metadata(payload: dict[str, Any]) -> None:
    """Remove loader-only keys before Pydantic validation."""

    raw_slides = payload.get("slides")
    if not isinstance(raw_slides, list):
        return
    for slide in raw_slides:
        if isinstance(slide, dict):
            slide.pop(_SLIDE_SOURCE_ROOT_KEY, None)


def _is_python_module_path_literal(raw_type: object) -> bool:
    """Return True when inline visual.type looks like a module path."""

    if not isinstance(raw_type, str):
        return False
    candidate = raw_type.strip()
    if not candidate:
        return False
    return (
        candidate.startswith(".")
        or candidate.endswith(".py")
        or "/" in candidate
        or "\\" in candidate
    )


def _rebase_path_literal(raw: object, *, from_root: Path, to_root: Path) -> object:
    """Translate a relative path literal from one base directory to another."""

    if not isinstance(raw, str):
        return raw

    candidate = raw.strip()
    if not candidate:
        return raw
    if "{{" in candidate or "}}" in candidate:
        return raw
    if is_registry_anchored_path(candidate):
        return raw

    path_obj = Path(candidate).expanduser()
    if path_obj.is_absolute():
        return str(path_obj.resolve(strict=False))

    absolute = (from_root / path_obj).resolve(strict=False)
    rebased = os.path.relpath(absolute, to_root)
    return Path(rebased).as_posix()


def _rebase_visual_fragment_paths(visual: dict[str, Any], *, from_root: Path, to_root: Path) -> None:
    """Rebase visual ref/type path literals for cross-pack patch merges."""

    if "ref" in visual:
        visual["ref"] = _rebase_path_literal(visual.get("ref"), from_root=from_root, to_root=to_root)

    if _is_python_module_path_literal(visual.get("type")):
        visual["type"] = _rebase_path_literal(visual.get("type"), from_root=from_root, to_root=to_root)


def _rebase_slide_fragment_paths(fragment: dict[str, Any], *, from_root: Path, to_root: Path) -> dict[str, Any]:
    """Rebase path-like fields inside a slide or slide patch payload."""

    rebased = copy.deepcopy(fragment)

    if "image" in rebased:
        rebased["image"] = _rebase_path_literal(rebased.get("image"), from_root=from_root, to_root=to_root)

    raw_visual = rebased.get("visual")
    if isinstance(raw_visual, Mapping):
        visual = {str(key): value for key, value in raw_visual.items()}
        _rebase_visual_fragment_paths(visual, from_root=from_root, to_root=to_root)
        rebased["visual"] = visual

    raw_placeholders = rebased.get("placeholders")
    if isinstance(raw_placeholders, Mapping):
        placeholders: dict[str, Any] = {}
        for placeholder_id, raw_placeholder in raw_placeholders.items():
            if not isinstance(raw_placeholder, Mapping):
                placeholders[str(placeholder_id)] = raw_placeholder
                continue

            placeholder = {str(key): value for key, value in raw_placeholder.items()}
            if "image" in placeholder:
                placeholder["image"] = _rebase_path_literal(
                    placeholder.get("image"),
                    from_root=from_root,
                    to_root=to_root,
                )

            placeholder_visual = placeholder.get("visual")
            if isinstance(placeholder_visual, Mapping):
                visual = {str(key): value for key, value in placeholder_visual.items()}
                _rebase_visual_fragment_paths(visual, from_root=from_root, to_root=to_root)
                placeholder["visual"] = visual

            placeholders[str(placeholder_id)] = placeholder

        rebased["placeholders"] = placeholders

    return rebased


def _read_pack_payload(path: Path) -> Mapping[str, Any]:
    """Load one pack YAML payload from disk."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - surfaced in CLI
        msg = f"Failed to read pack configuration at {path}"
        raise PackConfigError(msg) from exc

    try:
        payload: Any = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:  # pragma: no cover - surfaced in CLI
        msg = f"Invalid YAML in pack configuration {path}"
        raise PackConfigError(msg) from exc

    if not isinstance(payload, Mapping):
        msg = f"Pack configuration must be a mapping at {path}"
        raise PackConfigError(msg)

    return payload


def _deep_merge(base: dict[str, Any], update: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge mapping values while letting update win for non-mappings."""

    merged = dict(base)
    for key, value in update.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _require_slide_mapping(slide: object, *, pack_path: Path, label: str) -> dict[str, Any]:
    """Return a slide payload as a mutable mapping."""

    if not isinstance(slide, Mapping):
        raise PackConfigError(f"{pack_path}: {label} must be a mapping")
    return {str(key): value for key, value in slide.items()}


def _extract_slide_id(slide: Mapping[str, Any], *, pack_path: Path, label: str) -> str:
    """Extract and validate a slide id from a raw slide mapping."""

    raw_id = slide.get("id")
    if not isinstance(raw_id, str):
        raise PackConfigError(f"{pack_path}: {label} requires slide.id as a string")
    slide_id = raw_id.strip()
    if not slide_id:
        raise PackConfigError(f"{pack_path}: {label} requires a non-empty slide.id")
    return slide_id


def _index_slides_by_id(slides: list[dict[str, Any]], *, pack_path: Path, label: str) -> dict[str, int]:
    """Build an id -> index map and ensure ids are present and unique."""

    index: dict[str, int] = {}
    for position, slide in enumerate(slides):
        slide_id = _extract_slide_id(slide, pack_path=pack_path, label=f"{label} slide at index {position}")
        if slide_id in index:
            raise PackConfigError(f"{pack_path}: duplicate slide id '{slide_id}' in {label}")
        index[slide_id] = position
    return index


def _slide_source_root(slide: Mapping[str, Any], *, fallback: Path) -> Path:
    """Return the declaration root for a composed slide mapping."""

    raw = slide.get(_SLIDE_SOURCE_ROOT_KEY)
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser().resolve(strict=False)
    return fallback


def _apply_slide_operations(
    *,
    base_slides: list[dict[str, Any]],
    child_config: PackConfig,
    pack_path: Path,
) -> list[dict[str, Any]]:
    """Apply declarative slide operations to inherited slides."""

    slides = copy.deepcopy(base_slides)

    # Remove operations run first so later replace/update/insert targets resolve against the
    # post-removal layout and callers can reason about one deterministic sequence.
    for remove_index, slide_id in enumerate(child_config.slides_remove or []):
        index_by_id = _index_slides_by_id(
            slides,
            pack_path=pack_path,
            label=f"slides_remove[{remove_index}]",
        )
        target = index_by_id.get(slide_id)
        if target is None:
            raise PackConfigError(f"{pack_path}: slides_remove[{remove_index}] targets unknown id '{slide_id}'")
        del slides[target]

    # Replace operations swap the full slide payload while keeping order stable.
    for replace_index, operation in enumerate(child_config.slides_replace or []):
        index_by_id = _index_slides_by_id(
            slides,
            pack_path=pack_path,
            label=f"slides_replace[{replace_index}]",
        )
        target = index_by_id.get(operation.id)
        if target is None:
            raise PackConfigError(
                f"{pack_path}: slides_replace[{replace_index}] targets unknown id '{operation.id}'"
            )
        replacement = operation.slide.model_dump(mode="python", exclude_none=True)
        replacement[_SLIDE_SOURCE_ROOT_KEY] = str(pack_path.parent)
        slides[target] = replacement

    # Update operations deep-merge into existing slides by id.
    for update_index, operation in enumerate(child_config.slides_update or []):
        index_by_id = _index_slides_by_id(
            slides,
            pack_path=pack_path,
            label=f"slides_update[{update_index}]",
        )
        target = index_by_id.get(operation.id)
        if target is None:
            raise PackConfigError(
                f"{pack_path}: slides_update[{update_index}] targets unknown id '{operation.id}'"
            )

        existing = _require_slide_mapping(
            slides[target],
            pack_path=pack_path,
            label=f"slides_update[{update_index}] target",
        )
        target_root = _slide_source_root(existing, fallback=pack_path.parent)
        source_root = pack_path.parent
        patch_payload = operation.patch
        if target_root != source_root:
            # Patch payloads are authored in the child pack. Rebase relative
            # path literals so they still resolve against the inherited slide's
            # declaration root unless the author uses anchored paths.
            patch_payload = _rebase_slide_fragment_paths(
                operation.patch,
                from_root=source_root,
                to_root=target_root,
            )
        merged = _deep_merge(existing, patch_payload)

        merged_id = _extract_slide_id(
            merged,
            pack_path=pack_path,
            label=f"slides_update[{update_index}] result",
        )
        if merged_id != operation.id:
            raise PackConfigError(
                f"{pack_path}: slides_update[{update_index}] changed id from '{operation.id}' to '{merged_id}'"
            )
        slides[target] = merged

    # Insert operations add new slides relative to an anchor in current slide order.
    for insert_index, operation in enumerate(child_config.slides_insert or []):
        index_by_id = _index_slides_by_id(
            slides,
            pack_path=pack_path,
            label=f"slides_insert[{insert_index}]",
        )
        anchor_id = operation.before or operation.after
        assert anchor_id is not None
        anchor_position = index_by_id.get(anchor_id)
        if anchor_position is None:
            raise PackConfigError(
                f"{pack_path}: slides_insert[{insert_index}] anchor '{anchor_id}' was not found"
            )

        new_slide = operation.slide.model_dump(mode="python", exclude_none=True)
        new_id = _extract_slide_id(new_slide, pack_path=pack_path, label=f"slides_insert[{insert_index}].slide")
        if new_id in index_by_id:
            raise PackConfigError(f"{pack_path}: slides_insert[{insert_index}] would duplicate id '{new_id}'")

        insert_at = anchor_position if operation.before else anchor_position + 1
        new_slide[_SLIDE_SOURCE_ROOT_KEY] = str(pack_path.parent)
        slides.insert(insert_at, new_slide)

    return slides


def _compose_pack_payload(path: Path, *, stack: PackLoadStack = ()) -> dict[str, Any]:
    """Resolve one pack payload, including its extends chain and slide operations."""

    if path in stack:
        joined = " -> ".join(str(item) for item in (*stack, path))
        raise PackConfigError(f"Detected circular pack extends while loading {joined}")

    payload = _read_pack_payload(path)
    try:
        config = PackConfig.model_validate(payload)
    except ValidationError as exc:
        raise PackConfigError(str(exc)) from exc

    operation_fields = ("slides_remove", "slides_replace", "slides_update", "slides_insert")
    has_operations = any(field in config.model_fields_set for field in operation_fields)
    has_explicit_slides = "slides" in config.model_fields_set

    if config.extends is None:
        if has_operations:
            raise PackConfigError(f"{path}: slides_* operations require extends")
        payload = config.model_dump(
            mode="python",
            exclude_none=True,
            exclude={"extends", "slides_remove", "slides_replace", "slides_update", "slides_insert"},
        )
        raw_slides = payload.get("slides")
        if isinstance(raw_slides, list):
            _annotate_slide_source_roots(raw_slides, source_root=path.parent)
        return payload

    parent_path = (path.parent / config.extends).resolve()
    parent_payload = _compose_pack_payload(parent_path, stack=(*stack, path))

    root_overrides = config.model_dump(
        mode="python",
        exclude_none=True,
        exclude_unset=True,
        exclude={"extends", "slides", "slides_remove", "slides_replace", "slides_update", "slides_insert"},
    )
    merged_payload = _deep_merge(copy.deepcopy(parent_payload), root_overrides)

    if has_explicit_slides:
        slides = [slide.model_dump(mode="python", exclude_none=True) for slide in config.slides]
        _annotate_slide_source_roots(slides, source_root=path.parent)
        merged_payload["slides"] = slides
    elif has_operations:
        parent_slides = parent_payload.get("slides", [])
        if not isinstance(parent_slides, list):
            raise PackConfigError(f"{path}: inherited slides must be a list")
        merged_payload["slides"] = _apply_slide_operations(
            base_slides=[_require_slide_mapping(slide, pack_path=path, label="inherited slide") for slide in parent_slides],
            child_config=config,
            pack_path=path,
        )
    else:
        merged_payload["slides"] = copy.deepcopy(parent_payload.get("slides", []))

    return merged_payload


def load_pack_config(path: Path) -> PackConfig:
    """Load and validate a pack configuration from YAML."""

    resolved = path.expanduser().resolve()

    try:
        composed = _compose_pack_payload(resolved)
    except PackConfigError:
        raise
    except ValidationError as exc:  # pragma: no cover - surfaced in CLI
        raise PackConfigError(str(exc)) from exc
    except Exception as exc:
        raise PackConfigError(f"Failed to load pack configuration at {resolved}: {exc}") from exc

    try:
        slide_source_roots = _parse_slide_source_roots(composed)
        _strip_internal_slide_metadata(composed)
        pack = PackConfig.model_validate(composed)
    except ValidationError as exc:  # pragma: no cover - surfaced in CLI
        raise PackConfigError(str(exc)) from exc

    for slide, source_root in zip(pack.slides, slide_source_roots):
        slide.set_source_root(source_root)

    return pack


__all__ = ["PackConfigError", "load_pack_config"]
