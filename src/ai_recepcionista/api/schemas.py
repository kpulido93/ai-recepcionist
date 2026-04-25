from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    app_name: str = Field(alias="appName")
    version: str
    environment: str

    model_config = {"populate_by_name": True}


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    service: str
    checks: dict[str, bool]


class VersionResponse(BaseModel):
    version: str
    app_name: str = Field(alias="appName")
    stasis_app_name: str = Field(alias="stasisAppName")
    environment: str
    python_version: str = Field(alias="pythonVersion")

    model_config = {"populate_by_name": True}
