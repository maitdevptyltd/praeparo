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
    VisualSchemaBuilder,
    VisualSchemaRegistration,
    get_visual_schema_registration,
    iter_visual_schema_registrations,
    load_visual_definition,
    register_visual_schema,
    register_visual_type,
)
from .context import ContextLoadError, load_context_file, merge_context_payload, resolve_dax_context
from .context_models import VisualContextModel
from .dax_context import DAXContextModel
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
    "register_visual_schema",
    "register_visual_type",
    "ContextLoadError",
    "load_context_file",
    "merge_context_payload",
    "resolve_dax_context",
    "VisualCLIArgument",
    "VisualCLIOptions",
    "VisualCLIHooks",
    "VisualContextModel",
    "DAXContextModel",
    "VisualSchemaBuilder",
    "VisualSchemaRegistration",
    "get_visual_schema_registration",
    "iter_visual_schema_registrations",
]
