"""Schemas for the NoSQL database."""

from datetime import datetime, timezone
from typing import Annotated, Any, Callable, Optional

from bson import ObjectId
from pydantic import BaseModel, Field
from pydantic_core import core_schema

from poiesis.api.tes.models import Service, TesTask


class _ObjectIdPydanticAnnotation:
    # cf. https://stackoverflow.com/a/76837550

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: Any,
        _handler: Callable[[Any], core_schema.CoreSchema],
    ) -> core_schema.CoreSchema:
        def validate_from_str(input_value: str) -> ObjectId:
            return ObjectId(input_value)

        return core_schema.union_schema(
            [
                # check if it's an instance first before doing any further work
                core_schema.is_instance_schema(ObjectId),
                core_schema.no_info_plain_validator_function(validate_from_str),
            ],
            serialization=core_schema.to_string_ser_schema(),
        )


PydanticObjectId = Annotated[ObjectId, _ObjectIdPydanticAnnotation]


class TaskSchema(BaseModel):
    """Schema for Task documents in the NoSQL database."""

    id: Optional[PydanticObjectId] = Field(
        default_factory=PydanticObjectId, alias="_id"
    )
    name: str
    tags: dict[str, str] = Field(default_factory=dict)
    task_id: str
    user_id: str
    service_hash: str
    tes_version: str
    status: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: TesTask

    class Config:
        """Pydantic configuration."""

        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}


class ServiceSchema(BaseModel):
    """Schema for Service documents in the NoSQL database."""

    id: Optional[PydanticObjectId] = Field(default_factory=ObjectId, alias="_id")
    service_hash: str
    update_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: Service

    class Config:
        """Pydantic configuration."""

        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
