"""Schemas for the NoSQL database."""

from datetime import datetime, timezone
from typing import Annotated, Any, Callable, Optional

from bson import ObjectId
from pydantic import BaseModel, Field
from pydantic_core import core_schema

from poiesis.api.constants import PoiesisApiConstants
from poiesis.api.tes.models import Service, TesState, TesTask
from poiesis.cli.utils import get_version

constants = PoiesisApiConstants()


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
    """Schema for Task documents in the NoSQL database.

    Args:
        name: Name of the task either provided by the user or the default name
        tags: Tags of the task either provided by the user or empty, would be used for
            filtering tasks
        task_id: Generated ID of the task
        user_id: Unique user ID from the authentication service
        service_hash: Hash of the service document when the task is created
        state: State of the task which is initialized to INITIALIZING but this would
            be updated as the task progresses
        updated_at: Timestamp when the task is updated, this would happen by K8s job
            namely TeXaM and TOrc.
        data: Task data which would be updated by K8s job namely TeXaM and TOrc.

    Attributes:
        id: ID of the Database document
        name: Name of the task either provided by the user or the default name
        tags: Tags of the task either provided by the user or empty, would be used for
            filtering tasks
        task_id: Generated ID of the task
        user_id: Unique user ID from the authentication service
        service_hash: Hash of the service document when the task is created
        tes_version: Version of the TES against which the task is registered
        state: State of the task which is initialized to INITIALIZING
        created_at: Timestamp when the task is created
        updated_at: Timestamp when the task is updated
        data: Task data
    """

    id: Optional[PydanticObjectId] = Field(
        default_factory=PydanticObjectId, alias="_id", frozen=True
    )
    name: str = Field(default=constants.Task.NAME, frozen=True)
    tags: dict[str, str] = Field(default_factory=dict, frozen=True)
    task_id: str = Field(frozen=True)
    user_id: str = Field(frozen=True)
    service_hash: str = Field(frozen=True)
    tes_version: str = Field(default_factory=lambda: get_version(), frozen=True)
    state: TesState = Field(default=TesState.INITIALIZING)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), frozen=True
    )
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: TesTask

    class Config:
        """Pydantic configuration."""

        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str, TesState: lambda x: x.value}


class ServiceSchema(BaseModel):
    """Schema for Service documents in the NoSQL database.

    Args:
        id: ID of the Database document
        service_hash: Hash of the service document
        update_by: Unique user ID of the admin from the authentication service
        updated_at: Timestamp when the service is updated
        data: Service data

    Attributes:
        id: ID of the Database document
        service_hash: Hash of the service document
        update_by: Unique user ID from the authentication service
        created_at: Timestamp when the service is created
        updated_at: Timestamp when the service is updated
        data: Service data
    """

    id: Optional[PydanticObjectId] = Field(
        default_factory=ObjectId, alias="_id", frozen=True
    )
    service_hash: str = Field(frozen=True)
    update_by: str = Field(frozen=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), frozen=True
    )
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: Service = Field(frozen=True)

    class Config:
        """Pydantic configuration."""

        populate_by_name = True
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
