from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

TubeId = Annotated[str, Field(min_length=1, max_length=128)]
# StrictInt: rejects "5", 5.0, True — only genuine JSON integers are valid volumes.
PositiveUl = Annotated[StrictInt, Field(gt=0)]


class RegisterTubeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: TubeId
    balance_ul: PositiveUl


class ChildSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: TubeId
    amount_ul: PositiveUl


class SplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_id: TubeId
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    request_key: Annotated[str, Field(min_length=1, max_length=128)]
    children: Annotated[list[ChildSpec], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def _child_ids_unique(self) -> "SplitRequest":
        ids = [c.id for c in self.children]
        if len(ids) != len(set(ids)):
            raise ValueError("children ids must be unique within one split request")
        return self
