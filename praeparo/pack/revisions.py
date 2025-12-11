"""Revision helpers for pack runs.

This module keeps revision allocation logic out of the CLI wiring so the same
semantics can be exercised directly from tests. Revisions are intentionally
simple: a manifest persisted under the pack's artefact root tracks the latest
revision token and minor counter so subsequent runs can request either a full
revision bump or a minor increment.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from praeparo.visuals.dax.planner_core import slugify


logger = logging.getLogger(__name__)


RevisionStrategy = str | None


@dataclass
class RevisionInfo:
    """Allocated revision metadata for a pack run."""

    revision: str
    minor: int
    root: Path
    folder: Path
    pptx_name: str


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        return {"revision": None, "minor": 0, "history": []}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Revision manifest is unreadable; reinitialising", extra={"manifest": str(manifest_path)})
        return {"revision": None, "minor": 0, "history": []}


def _store_manifest(manifest_path: Path, manifest: Mapping[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _normalise_revision_token(raw: str) -> str:
    """Make a filesystem-friendly revision token while keeping human cues."""

    cleaned = []
    previous_sep = False
    for char in raw.strip():
        if char.isalnum():
            cleaned.append(char.lower())
            previous_sep = False
            continue
        if char in "-_":
            if not previous_sep:
                cleaned.append(char)
                previous_sep = True
            continue
        if not previous_sep:
            cleaned.append("_")
            previous_sep = True
    token = "".join(cleaned).strip("-_")
    return token or "rev"


def _derive_context_revision(context: Mapping[str, Any]) -> str | None:
    """Prefer the month in context (YYYY-MM) when present."""

    month_value = context.get("month")
    if isinstance(month_value, str):
        try:
            parsed = datetime.fromisoformat(month_value)
            return f"{parsed.year:04d}-{parsed.month:02d}"
        except ValueError:
            pass
    return None


def _increment_token(token: str | None) -> str:
    if not token:
        return "r1"
    match = re.search(r"(.*?)(\d+)$", token)
    if match:
        prefix, number = match.groups()
        return f"{prefix}{int(number) + 1}"
    return f"{token}-1"


def _build_pptx_name(pack_path: Path, revision: str, minor: int) -> str:
    pack_slug = slugify(pack_path.stem)
    revision_token = _normalise_revision_token(revision)
    suffix = revision_token if minor <= 1 else f"{revision_token}_r{minor}"
    return f"{pack_slug}_{suffix}.pptx"


def allocate_revision(
    pack_path: Path,
    artefact_root: Path,
    pack_context: Mapping[str, Any],
    *,
    strategy: RevisionStrategy,
    override: str | None,
    dry_run: bool = False,
) -> RevisionInfo | None:
    """Allocate a revision token (and optional minor) for a pack run.

    Returns None when no revision semantics apply (no override, no strategy,
    and no obvious month in context).
    """

    revision_store = artefact_root.parent / "_revisions"
    manifest_path = revision_store / "manifest.json"
    manifest = _load_manifest(manifest_path)
    context_revision = _derive_context_revision(pack_context)

    revision: str | None = None
    minor = 1
    history_entry: dict[str, Any] | None = None
    if override:
        revision = override
    elif strategy:
        previous_revision = manifest.get("revision")
        previous_minor = int(manifest.get("minor") or 0)
        if strategy == "full":
            revision = context_revision or _increment_token(previous_revision)
            minor = 1
        elif strategy == "minor":
            revision = previous_revision or context_revision or "r1"
            minor = previous_minor + 1 if previous_revision == revision else 1
        else:
            raise ValueError(f"Unknown revision strategy '{strategy}'")
        history_entry = {
            "revision": revision,
            "minor": minor,
            "strategy": strategy,
            "context_month": context_revision,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    else:
        revision = context_revision
        minor = 1

    if revision is None:
        return None

    revision_token = _normalise_revision_token(str(revision))
    root = revision_store / revision_token
    folder = root / f"rev={minor:02d}"
    pptx_name = _build_pptx_name(pack_path, revision_token, minor)

    if dry_run:
        logger.info(
            "Revision dry run",
            extra={
                "revision": revision_token,
                "minor": minor,
                "pptx_name": pptx_name,
                "folder": str(folder),
            },
        )
        return RevisionInfo(
            revision=revision_token,
            minor=minor,
            root=root,
            folder=folder,
            pptx_name=pptx_name,
        )

    if history_entry:
        history = list(manifest.get("history") or [])
        history.append(history_entry)
        manifest.update({"revision": revision_token, "minor": minor, "history": history})
        _store_manifest(manifest_path, manifest)

    return RevisionInfo(
        revision=revision_token,
        minor=minor,
        root=root,
        folder=folder,
        pptx_name=pptx_name,
    )


__all__ = ["RevisionInfo", "allocate_revision"]
