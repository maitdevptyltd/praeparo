"""Shared visual configuration utilities."""

from .metrics import (
    CalculateInput,
    VisualGroupConfig,
    VisualMetricConfig,
    VisualMetricMock,
    VisualMetricMockScenario,
    VisualMetricMockScenarioOverride,
    VisualMockConfig,
    normalise_str_sequence,
)
from .registry import (
    VisualCLIArgument,
    VisualCLIOptions,
    VisualCLIHooks,
    VisualLoader,
    load_visual_definition,
    register_visual_type,
)
from .context import ContextLoadError, load_context_file, merge_context_payload

__all__ = [
    "CalculateInput",
    "VisualGroupConfig",
    "VisualLoader",
    "VisualMetricConfig",
    "VisualMetricMock",
    "VisualMetricMockScenario",
    "VisualMetricMockScenarioOverride",
    "VisualMockConfig",
    "load_visual_definition",
    "normalise_str_sequence",
    "register_visual_type",
    "ContextLoadError",
    "load_context_file",
    "merge_context_payload",
    "VisualCLIArgument",
    "VisualCLIOptions",
    "VisualCLIHooks",
]
