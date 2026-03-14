from __future__ import annotations

import asyncio

from praeparo.mcp_server import build_mcp_server


def test_build_mcp_server_registers_expected_tools() -> None:
    server = build_mcp_server()

    tools = asyncio.run(server.list_tools())
    tool_names = {tool.name for tool in tools}

    assert "render_pack_slide" in tool_names
    assert "compare_pack_render" in tool_names
    assert "inspect_pack_render" in tool_names
    assert "approve_pack_render" in tool_names
    assert "review_pack_render" in tool_names
    assert "inspect_visual" in tool_names
    assert "compare_visual_render" in tool_names
    assert "approve_visual_render" in tool_names
    assert "review_visual_render" in tool_names
    assert "read_manifest" in tool_names
