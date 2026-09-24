from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MIN_CHILDREN = 1
MAX_CHILDREN = 20
MAX_AMOUNT = 1_000_000_000  # sanity bound for a single tube (µL)


class StrictModel(BaseModel):
    """Strict parsing: unknown fields and type coercions are rejected with 422."""

    model_config = ConfigDict(strict=True, extra="forbid")


def _non_blank(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("must not be blank")
    return value.strip()


class RegisterTubeIn(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    initial_amount: int = Field(gt=0, le=MAX_AMOUNT)

    _id_non_blank = field_validator("id")(_non_blank)


class ChildIn(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    amount: int = Field(gt=0, le=MAX_AMOUNT)

    _id_non_blank = field_validator("id")(_non_blank)


class SplitIn(StrictModel):
    parent_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    request_key: str = Field(min_length=1, max_length=200)
    children: list[ChildIn] = Field(min_length=MIN_CHILDREN, max_length=MAX_CHILDREN)

    _parent_non_blank = field_validator("parent_id")(_non_blank)
    _key_non_blank = field_validator("request_key")(_non_blank)

    @model_validator(mode="after")
    def _validate_child_ids(self) -> "SplitIn":
        seen: set[str] = set()
        for child in self.children:
            if child.id in seen:
                raise ValueError(f"duplicate child id in request: {child.id}")
            if child.id == self.parent_id:
                raise ValueError("a child id must differ from the parent id")
            seen.add(child.id)
        return self
