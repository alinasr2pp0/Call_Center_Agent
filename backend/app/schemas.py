"""Pydantic v2 request models (responses are plain dicts built in the routers)."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50)]
_USERNAME_RE = re.compile(r"^[\w.\-@]+$", re.UNICODE)


def _check_username(value: str) -> str:
    if not _USERNAME_RE.match(value):
        raise ValueError("username may only contain letters, digits and . _ - @")
    return value


class LoginRequest(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    password: Annotated[str, Field(min_length=1, max_length=256)]


# ---- customers ----
class CustomerSignup(BaseModel):
    username: Username
    password: Annotated[str, Field(min_length=8, max_length=128)]
    phone: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    name: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]] = None

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return _check_username(v)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v)
        if not 8 <= len(digits) <= 15:
            raise ValueError("phone number must contain 8 to 15 digits")
        return v


class CustomerLogin(LoginRequest):
    pass


class PasswordReset(BaseModel):
    new_password: Annotated[str, Field(min_length=6, max_length=128)]


class ActiveFlag(BaseModel):
    is_active: bool


# ---- tickets ----
class ProblemMessage(BaseModel):
    problem_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    persona_id: Optional[str] = None


class TtsRequest(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


# ---- staff ----
class StaffCreate(BaseModel):
    username: Username
    password: Annotated[str, Field(min_length=6, max_length=128)]
    role: Literal["agent", "admin"] = "agent"

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return _check_username(v)


class StaffRoleUpdate(BaseModel):
    role: Literal["agent", "admin"]


# ---- knowledge base ----
class KBArticleIn(BaseModel):
    product: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    ticket_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)] = ""
    resolution: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=20000)]] = None
    status: Literal["Open", "Pending Customer Response", "Closed"] = "Open"
    priority: Literal["Low", "Medium", "High", "Critical"] = "Medium"
    channel: Literal["Phone", "Email", "Chat", "Social media"] = "Phone"


# ---- personas ----
class PersonaUpdate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    role: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]] = None
    description: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]] = None
    tone_instructions_ar: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = ""
    is_default: bool = False
    verbosity: Optional[Literal["short", "medium", "detailed"]] = None
    max_words: Optional[Annotated[int, Field(ge=20, le=500)]] = None
