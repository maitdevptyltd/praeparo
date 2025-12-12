from __future__ import annotations

import logging
from io import StringIO
from typing import Iterator

import pytest

from praeparo.cli import INCLUDE_THIRD_PARTY_LOGS_ENV_VAR, LOG_LEVEL_ENV_VAR, _configure_logging


@pytest.fixture()
def _restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    previous_level = root.level

    try:
        yield
    finally:
        root.handlers.clear()
        root.setLevel(previous_level)


def test_configure_logging_filters_non_praeparo_logs(monkeypatch, _restore_logging) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENV_VAR, raising=False)
    monkeypatch.delenv(INCLUDE_THIRD_PARTY_LOGS_ENV_VAR, raising=False)

    _configure_logging("DEBUG", include_third_party_logs=False)

    root = logging.getLogger()
    stream = StringIO()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(stream)

    praeparo_logger = logging.getLogger("praeparo.test")
    third_party_logger = logging.getLogger("httpx")

    praeparo_logger.debug("praeparo-debug")
    third_party_logger.info("third-party-info")
    third_party_logger.warning("third-party-warning")

    for handler in root.handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    output = stream.getvalue()
    assert "praeparo-debug" in output
    assert "third-party-info" not in output
    assert "third-party-warning" in output


def test_configure_logging_includes_third_party_when_enabled(monkeypatch, _restore_logging) -> None:
    monkeypatch.delenv(LOG_LEVEL_ENV_VAR, raising=False)
    monkeypatch.delenv(INCLUDE_THIRD_PARTY_LOGS_ENV_VAR, raising=False)

    _configure_logging("INFO", include_third_party_logs=True)

    root = logging.getLogger()
    stream = StringIO()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(stream)

    third_party_logger = logging.getLogger("httpx")
    third_party_logger.info("third-party-info")

    for handler in root.handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    output = stream.getvalue()
    assert "third-party-info" in output
