from __future__ import annotations

from praeparo.pipeline import PythonVisualBase
from praeparo.visuals.context_models import VisualContextModel


class _Context(VisualContextModel):
    pass


class FirstVisual(PythonVisualBase[list[int], _Context]):
    context_model = _Context


class SecondVisual(PythonVisualBase[list[int], _Context]):
    context_model = _Context
