"""Thin MCP wrapper over the canonical Praeparo CLI workflows.

The CLI remains the source of truth for render, compare, approve, and review
behaviour. This server intentionally shells back into those same commands so
MCP clients and human operators see one set of contracts, one artefact layout,
and one set of failure modes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Literal, Sequence

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from praeparo.visuals.dax import slugify


class MCPCommandResult(BaseModel):
    """Structured result for one Praeparo CLI invocation from MCP."""

    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    manifest_path: str | None = None
    manifest: dict[str, object] | None = None


def build_mcp_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
) -> FastMCP:
    """Build the Praeparo MCP server around the stable CLI surface."""

    server = FastMCP(
        name="Praeparo",
        instructions=(
            "Thin wrapper over the Praeparo CLI for focused render, compare, approve, "
            "and review workflows."
        ),
        host=host,
        port=port,
        log_level=log_level,
    )

    @server.tool(description="Render one or more pack slides and return the emitted render manifest.")
    def render_pack_slide(
        pack_path: str,
        artefact_dir: str,
        slides: list[str],
        *,
        project_root: str | None = None,
        data_mode: str | None = None,
        plugins: list[str] | None = None,
        include_evidence: bool = False,
        allow_partial: bool = False,
    ) -> MCPCommandResult:
        command = ["pack", "render-slide", pack_path, "--artefact-dir", artefact_dir]
        command = _append_repeatable_flag(command, "--slide", slides)
        command = _append_repeatable_flag(command, "--plugin", plugins or [])
        if project_root:
            command.extend(["--project-root", project_root])
        if data_mode:
            command.extend(["--data-mode", data_mode])
        if include_evidence:
            command.append("--include-evidence")
        if allow_partial:
            command.append("--allow-partial")

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=Path(artefact_dir) / "render.manifest.json",
        )

    @server.tool(description="Compare a focused pack render to its approved baselines.")
    def compare_pack_render(
        source: str,
        baseline_dir: str,
        *,
        project_root: str | None = None,
        slides: list[str] | None = None,
        output_dir: str | None = None,
    ) -> MCPCommandResult:
        command = ["pack", "compare-slide", source, "--baseline-dir", baseline_dir]
        command = _append_repeatable_flag(command, "--slide", slides or [])
        if project_root:
            command.extend(["--project-root", project_root])
        manifest_output_dir = Path(output_dir) if output_dir else _source_root(Path(source)) / "_comparisons"
        if output_dir:
            command.extend(["--output-dir", output_dir])

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=manifest_output_dir / "compare.manifest.json",
        )

    @server.tool(description="Inspect one rendered pack target and return its diagnosis payload.")
    def inspect_pack_render(
        source: str,
        slide: str,
        *,
        project_root: str | None = None,
        compare_manifest: str | None = None,
        output_path: str | None = None,
    ) -> MCPCommandResult:
        command = ["pack", "inspect-slide", source, "--slide", slide]
        if compare_manifest:
            command.extend(["--compare-manifest", compare_manifest])
        if project_root:
            command.extend(["--project-root", project_root])

        resolved_output_path = (
            Path(output_path)
            if output_path is not None
            else _source_root(Path(source)) / "_mcp" / f"{slugify(slide)}.inspect.json"
        )
        command.extend(["--output", str(resolved_output_path)])

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=resolved_output_path,
        )

    @server.tool(description="Approve selected pack render targets into a baseline directory.")
    def approve_pack_render(
        source: str,
        baseline_dir: str,
        slides: list[str],
        *,
        project_root: str | None = None,
        note: str | None = None,
    ) -> MCPCommandResult:
        command = ["pack", "approve-slide", source, "--baseline-dir", baseline_dir]
        command = _append_repeatable_flag(command, "--slide", slides)
        if project_root:
            command.extend(["--project-root", project_root])
        if note:
            command.extend(["--note", note])

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=Path(baseline_dir) / "baseline.manifest.json",
        )

    @server.tool(description="Build a human-reviewable bundle for focused pack verification.")
    def review_pack_render(
        source: str,
        baseline_dir: str,
        *,
        project_root: str | None = None,
        slides: list[str] | None = None,
        output_path: str | None = None,
    ) -> MCPCommandResult:
        command = ["pack", "review", source, "--baseline-dir", baseline_dir]
        command = _append_repeatable_flag(command, "--slide", slides or [])
        if project_root:
            command.extend(["--project-root", project_root])

        resolved_output_path = (
            Path(output_path)
            if output_path is not None
            else _source_root(Path(source)) / "_review" / "review.manifest.json"
        )
        command.extend(["--output", str(resolved_output_path)])

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=resolved_output_path,
        )

    @server.tool(description="Run one standalone visual inspection and return the emitted render manifest.")
    def inspect_visual(
        visual_type: str,
        config_path: str,
        artefact_dir: str,
        *,
        project_root: str | None = None,
        data_mode: str | None = None,
        plugins: list[str] | None = None,
    ) -> MCPCommandResult:
        command = ["visual", "inspect", visual_type, config_path, "--artefact-dir", artefact_dir]
        command = _append_repeatable_flag(command, "--plugin", plugins or [])
        if project_root:
            command.extend(["--project-root", project_root])
        if data_mode:
            command.extend(["--data-mode", data_mode])

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=Path(artefact_dir) / "render.manifest.json",
        )

    @server.tool(description="Compare one visual inspection render to its approved baseline.")
    def compare_visual_render(
        source: str,
        baseline_dir: str,
        *,
        project_root: str | None = None,
        output_dir: str | None = None,
    ) -> MCPCommandResult:
        command = ["visual", "compare", source, "--baseline-dir", baseline_dir]
        if project_root:
            command.extend(["--project-root", project_root])
        manifest_output_dir = Path(output_dir) if output_dir else _source_root(Path(source)) / "_comparisons"
        if output_dir:
            command.extend(["--output-dir", output_dir])

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=manifest_output_dir / "compare.manifest.json",
        )

    @server.tool(description="Approve a standalone visual render into its baseline directory.")
    def approve_visual_render(
        source: str,
        baseline_dir: str,
        *,
        project_root: str | None = None,
        note: str | None = None,
    ) -> MCPCommandResult:
        command = ["visual", "approve", source, "--baseline-dir", baseline_dir]
        if project_root:
            command.extend(["--project-root", project_root])
        if note:
            command.extend(["--note", note])

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=Path(baseline_dir) / "baseline.manifest.json",
        )

    @server.tool(description="Build a human-reviewable bundle for standalone visual verification.")
    def review_visual_render(
        source: str,
        baseline_dir: str,
        *,
        project_root: str | None = None,
        output_path: str | None = None,
    ) -> MCPCommandResult:
        command = ["visual", "review", source, "--baseline-dir", baseline_dir]
        if project_root:
            command.extend(["--project-root", project_root])

        resolved_output_path = (
            Path(output_path)
            if output_path is not None
            else _source_root(Path(source)) / "_review" / "review.manifest.json"
        )
        command.extend(["--output", str(resolved_output_path)])

        return _run_cli_command(
            command,
            cwd=Path(project_root).expanduser().resolve(strict=False) if project_root else Path.cwd().resolve(),
            manifest_path=resolved_output_path,
        )

    @server.tool(description="Load a JSON manifest emitted by Praeparo.")
    def read_manifest(path: str) -> dict[str, object]:
        resolved = Path(path).expanduser().resolve(strict=False)
        return _load_json_manifest(resolved) or {}

    return server


def run_mcp_server(
    *,
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
) -> None:
    """Start the Praeparo MCP server over the requested transport."""

    build_mcp_server(host=host, port=port, log_level=log_level).run(transport=transport)


def _run_cli_command(
    command: Sequence[str],
    *,
    cwd: Path,
    manifest_path: Path | None = None,
) -> MCPCommandResult:
    """Run the canonical CLI and load the expected manifest when it appears.

    Start by invoking `python -m praeparo.cli` so MCP stays coupled to the same
    parser and handlers that humans use in the terminal. Then, if the command
    produced a known manifest path, load it into the response for immediate
    structured inspection.
    """

    full_command = [sys.executable, "-m", "praeparo.cli", *command]
    completed = subprocess.run(
        full_command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )

    resolved_manifest_path = None if manifest_path is None else _resolve_result_path(manifest_path, cwd=cwd)
    manifest = _load_json_manifest(resolved_manifest_path) if resolved_manifest_path is not None else None

    return MCPCommandResult(
        command=full_command,
        cwd=str(cwd),
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        manifest_path=str(resolved_manifest_path) if resolved_manifest_path is not None else None,
        manifest=manifest,
    )


def _append_repeatable_flag(command: list[str], flag: str, values: Sequence[str]) -> list[str]:
    """Append one CLI flag for each supplied value and return the same list."""

    for value in values:
        command.extend([flag, value])
    return command


def _source_root(source: Path) -> Path:
    """Resolve the artefact root for a render source path or manifest path."""

    return source if source.suffix != ".json" else source.parent


def _resolve_result_path(path: Path, *, cwd: Path) -> Path:
    """Resolve a manifest path relative to the working directory used for the CLI."""

    if path.is_absolute():
        return path.expanduser().resolve(strict=False)
    return (cwd / path).expanduser().resolve(strict=False)


def _load_json_manifest(path: Path | None) -> dict[str, object] | None:
    """Load one JSON manifest if it exists and has the expected top-level shape."""

    if path is None or not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload
    return {"value": payload}


__all__ = [
    "MCPCommandResult",
    "build_mcp_server",
    "run_mcp_server",
]
