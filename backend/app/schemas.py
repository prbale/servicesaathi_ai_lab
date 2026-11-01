"""Pydantic request/response schemas: the API's validated contract."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Category = Literal["plumbing", "electrical", "appliance"]
TimeWindow = str  # "morning" | "afternoon" | "evening" | "any" | "at:HH"


def _check_window(v: str) -> str:
    if v in ("morning", "afternoon", "evening", "any"):
        return v
    if v.startswith("at:") and v[3:].isdigit() and 6 <= int(v[3:]) <= 21:
        return v
    raise ValueError("time_window must be morning, afternoon, evening, any, or at:HH (06–21)")


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class SearchIn(BaseModel):
    category: Category
    locality: str = Field(min_length=2, max_length=50)
    preferred_date: date
    time_window: TimeWindow = "any"

    _w = field_validator("time_window")(_check_window)


class BookingIn(BaseModel):
    slot_id: int = Field(gt=0)
    technician_id: int = Field(gt=0)
    category: Category
    locality: str = Field(min_length=2, max_length=50)
    issue_description: str = Field(min_length=3, max_length=1000)


class StatusChangeIn(BaseModel):
    to_status: Literal["en_route", "in_progress", "completed", "cancelled_by_provider", "cancelled_by_customer"]
    reason: str = Field(default="", max_length=300)


class SlotIn(BaseModel):
    date: date
    hour: int = Field(ge=6, le=21)


class InterpretIn(BaseModel):
    text: str = Field(min_length=3, max_length=1000)
    # Corrections from the editable summary / follow-up answers. Each wins over extraction.
    overrides: dict[str, str] = Field(default_factory=dict)
    mode: Literal["auto", "rules", "llm"] = "auto"


class PolicyQuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class TechnicianIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    bio: str = Field(default="", max_length=300)
    years_experience: int = Field(ge=0, le=60)
    rating: float = Field(ge=0, le=5)
    is_active: bool = True
    charges: dict[Category, int] = Field(description="category -> visiting charge INR")
    localities: list[str] = Field(min_length=1)

    @field_validator("charges")
    @classmethod
    def _charges(cls, v):
        if not v:
            raise ValueError("at least one category is required")
        for amount in v.values():
            if not 1 <= amount <= 100000:
                raise ValueError("visiting charge must be between 1 and 100000 INR")
        return v


class LocalityIn(BaseModel):
    code: str = Field(pattern=r"^[a-z_]{2,30}$")
    name: str = Field(min_length=2, max_length=50)
    aliases: list[str] = Field(default_factory=list)


class CategoryUpdateIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    description: str = Field(default="", max_length=300)


class ResetIn(BaseModel):
    confirm: str
