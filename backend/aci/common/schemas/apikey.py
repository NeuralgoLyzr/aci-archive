from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from aci.common.enums import APIKeyStatus


class APIKeyPublic(BaseModel):
    id: UUID
    agent_id: UUID
    status: APIKeyStatus

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class APIKeyWithSecret(APIKeyPublic):
    """APIKeyPublic plus the plaintext key.

    Only for creation-time responses (project/agent creation), where the caller
    must capture the key once. Never use as the response model for read endpoints.
    """

    key: str
