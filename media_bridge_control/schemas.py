"""Strict Admin API request contracts."""

from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints

from media_bridge.contracts import StrictModel


class AdminStrictModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Username = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$"),
]
Password = Annotated[str, StringConstraints(min_length=12, max_length=1_024)]


class BootstrapRequest(AdminStrictModel):
    username: Username
    password: Password


class LoginRequest(AdminStrictModel):
    username: Username
    password: Annotated[str, StringConstraints(min_length=1, max_length=1_024)]


class SafeAdminError(AdminStrictModel):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class SafeAdminErrorEnvelope(AdminStrictModel):
    error: SafeAdminError = Field()
