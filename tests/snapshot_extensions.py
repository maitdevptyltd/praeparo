from typing import ClassVar

from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode


class NamedSingleFileSnapshotExtension(SingleFileSnapshotExtension):
    """Single file snapshot that allows overriding the snapshot file name."""

    snapshot_name: ClassVar[str | None] = None

    @classmethod
    def get_snapshot_name(cls, *, test_location, index=0):  # type: ignore[override]
        if cls.snapshot_name:
            return cls.snapshot_name
        return super().get_snapshot_name(test_location=test_location, index=index)


class PlotlyHtmlSnapshotExtension(NamedSingleFileSnapshotExtension):
    """Store Plotly HTML output as human-readable snapshot files."""

    _write_mode = WriteMode.TEXT
    _file_extension = "html"

    def serialize(self, data, *, exclude=None, include=None, matcher=None):  # type: ignore[override]
        if not isinstance(data, str):
            msg = "Plotly HTML snapshots expect a string payload."
            raise TypeError(msg)
        return data.replace("\r\n", "\n")


class PlotlyPngSnapshotExtension(NamedSingleFileSnapshotExtension):
    """Persist Plotly PNG bytes for inspection."""

    _write_mode = WriteMode.BINARY
    _file_extension = "png"

    def serialize(self, data, *, exclude=None, include=None, matcher=None):  # type: ignore[override]
        if isinstance(data, (bytes, bytearray, memoryview)):
            return bytes(data)
        msg = "Plotly PNG snapshots expect binary data."
        raise TypeError(msg)


class DaxSnapshotExtension(NamedSingleFileSnapshotExtension):
    """Capture generated DAX statements as text snapshots."""

    _write_mode = WriteMode.TEXT
    _file_extension = "dax"

    def serialize(self, data, *, exclude=None, include=None, matcher=None):  # type: ignore[override]
        if not isinstance(data, str):
            msg = "DAX snapshots expect string content."
            raise TypeError(msg)
        return data.replace("\r\n", "\n")


__all__ = [
    "NamedSingleFileSnapshotExtension",
    "PlotlyHtmlSnapshotExtension",
    "PlotlyPngSnapshotExtension",
    "DaxSnapshotExtension",
]
