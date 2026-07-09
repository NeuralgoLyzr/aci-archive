from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aci.common.db.sql_models import MAX_STRING_LENGTH, SecurityScheme
from aci.common.schemas.security_scheme import (
    APIKeySchemeCredentials,
    APIKeySchemeCredentialsLimited,
    NoAuthSchemeCredentials,
    NoAuthSchemeCredentialsLimited,
    OAuth2SchemeCredentials,
    OAuth2SchemeCredentialsLimited,
)


class LinkedAccountCreateBase(BaseModel):
    app_name: str
    linked_account_owner_id: str


class LinkedAccountCreateByAppIdBase(BaseModel):
    app_id: UUID
    linked_account_owner_id: str


class LinkedAccountOAuth2Create(LinkedAccountCreateBase):
    after_oauth2_link_redirect_url: str | None = None


class LinkedAccountOAuth2CreateByAppId(LinkedAccountCreateByAppIdBase):
    after_oauth2_link_redirect_url: str | None = None


class LinkedAccountAPIKeyCreate(LinkedAccountCreateBase):
    api_key: str


class LinkedAccountAPIKeyCreateByAppId(LinkedAccountCreateByAppIdBase):
    api_key: str


class LinkedAccountDefaultCreate(LinkedAccountCreateBase):
    pass


class LinkedAccountNoAuthCreate(LinkedAccountCreateBase):
    pass


class LinkedAccountNoAuthCreateByAppId(LinkedAccountCreateByAppIdBase):
    pass


class LinkedAccountUpdate(BaseModel):
    enabled: bool | None = None


class LinkedAccountOAuth2CreateState(BaseModel):
    project_id: UUID
    app_name: str
    linked_account_owner_id: str = Field(..., max_length=MAX_STRING_LENGTH)
    # The OAuth2 client ID used at the start of the OAuth2 flow. We need to store this and verify in the callback
    # because we support custom client ID, and user may have changed the client ID after the flow starts.
    # (e.g., delete and recreate app configuration. Even though this is rare.)
    client_id: str
    code_verifier: str
    after_oauth2_link_redirect_url: str | None = None
    # Optional app_id for by-app-id flow
    app_id: UUID | None = None


class LinkedAccountPublic(BaseModel):
    id: UUID
    project_id: UUID
    app_name: str
    app_id: UUID
    linked_account_owner_id: str
    security_scheme: SecurityScheme
    # NOTE: unnecessary to expose the security credentials
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class LinkedAccountWithCredentials(LinkedAccountPublic):
    security_credentials: (
        OAuth2SchemeCredentialsLimited
        | APIKeySchemeCredentialsLimited
        | NoAuthSchemeCredentialsLimited
    )


class LinkedAccountWithFullCredentials(LinkedAccountPublic):
    """
    Like LinkedAccountWithCredentials, but exposes the full, unredacted credentials
    for every security scheme — including the raw secret_key for api_key-based
    linked accounts, which LinkedAccountWithCredentials deliberately withholds.
    """

    security_credentials: (
        OAuth2SchemeCredentials | APIKeySchemeCredentials | NoAuthSchemeCredentials
    )


class LinkedAccountOAuth2ClientCredentialsCreate(BaseModel):
    app_name: str
    linked_account_owner_id: str
    tenant_id: str | None = None
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scope: str | None = None

    @model_validator(mode="after")
    def validate_token_url_or_tenant_id(self) -> "LinkedAccountOAuth2ClientCredentialsCreate":
        if not self.tenant_id and not self.token_url:
            raise ValueError("Either tenant_id or token_url must be provided")
        return self


class LinkedAccountsList(BaseModel):
    app_name: str | None = None
    linked_account_owner_id: str | None = None
