from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PowerBIDataSourceConfig(BaseModel):
    """Declarative configuration for connecting to a Power BI dataset."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["powerbi"] = Field(default="powerbi", description="Data source discriminator.")
    dataset_id: str | None = Field(
        default=None,
        alias="datasetId",
        description="Dataset identifier or environment placeholder.",
    )
    workspace_id: str | None = Field(
        default=None,
        alias="workspaceId",
        description="Optional workspace (group) id or environment placeholder.",
    )
    tenant_id: str | None = Field(
        default=None,
        alias="tenantId",
        description="Optional tenant override for authentication.",
    )
    client_id: str | None = Field(
        default=None,
        alias="clientId",
        description="Optional client id override for authentication.",
    )
    client_secret: str | None = Field(
        default=None,
        alias="clientSecret",
        description="Optional client secret override for authentication.",
    )
    refresh_token: str | None = Field(
        default=None,
        alias="refreshToken",
        description="Optional refresh token override for authentication.",
    )
    scope: str | None = Field(
        default=None,
        description="Optional OAuth scope override for authentication.",
    )

    @field_validator(
        "dataset_id",
        "workspace_id",
        "tenant_id",
        "client_id",
        "client_secret",
        "refresh_token",
        "scope",
    )
    @classmethod
    def _normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


__all__ = ["PowerBIDataSourceConfig"]
