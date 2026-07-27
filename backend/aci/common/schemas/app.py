import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from aci.common.enums import SecurityScheme, Visibility
from aci.common.schemas.function import BasicFunctionDefinition, FunctionDetails
from aci.common.schemas.security_scheme import (
    APIKeyScheme,
    APIKeySchemeCredentials,
    NoAuthScheme,
    NoAuthSchemeCredentials,
    OAuth2Scheme,
    OAuth2SchemeCredentials,
    SecuritySchemesLocations,
    SecuritySchemesPublic,
)

# Maps each known SecurityScheme to the Pydantic model that validates its config.
# Extend this dict when adding new scheme types (e.g. http_basic, http_bearer).
_SCHEME_MODELS: dict[SecurityScheme, type[BaseModel]] = {
    SecurityScheme.NO_AUTH: NoAuthScheme,
    SecurityScheme.API_KEY: APIKeyScheme,
    SecurityScheme.OAUTH2: OAuth2Scheme,
}


class AppUpsert(BaseModel, extra="forbid"):
    name: str
    display_name: str
    provider: str
    version: str
    description: str
    logo: str
    categories: list[str]
    visibility: Visibility
    active: bool
    # TODO: consider refactor and use discriminator for security_schemes/default_security_credentials_by_scheme
    security_schemes: dict[SecurityScheme, APIKeyScheme | OAuth2Scheme | NoAuthScheme]
    default_security_credentials_by_scheme: dict[
        SecurityScheme, APIKeySchemeCredentials | OAuth2SchemeCredentials | NoAuthSchemeCredentials
    ]

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r"^[A-Z0-9_]+$", v) or "__" in v:
            raise ValueError(
                "name must be uppercase, contain only letters, numbers and underscores, and not have consecutive underscores"
            )
        return v

    @field_validator("security_schemes", mode="before")
    @classmethod
    def validate_security_schemes(
        cls, v: Any
    ) -> dict[SecurityScheme, APIKeyScheme | OAuth2Scheme | NoAuthScheme]:
        """
        Validate each security scheme entry against its specific model class.

        Running in mode="before" so we intercept the raw dict before Pydantic's
        union parser tries all branches and produces noisy multi-branch errors.
        Returning already-instantiated model objects lets Pydantic accept them
        without re-running union validation.
        """
        if not isinstance(v, dict):
            raise ValueError("must be a dict")

        valid_types = ", ".join(s.value for s in SecurityScheme)
        errors: list[str] = []
        result: dict[SecurityScheme, APIKeyScheme | OAuth2Scheme | NoAuthScheme] = {}

        for key, value in v.items():
            try:
                scheme_type = SecurityScheme(key)
            except ValueError:
                errors.append(f"{key}: Unknown scheme type. Allowed: {valid_types}")
                continue

            model_cls = _SCHEME_MODELS.get(scheme_type)
            if model_cls is None:
                errors.append(f"{key}: Scheme type '{key}' is not yet supported")
                continue

            if not isinstance(value, dict):
                errors.append(f"{key}: must be a dict, got {type(value).__name__}")
                continue

            try:
                result[scheme_type] = model_cls.model_validate(value)
            except ValidationError as e:
                for err in e.errors():
                    loc = err["loc"]
                    field = ".".join(str(p) for p in loc) if loc else None
                    path = f"{key}.{field}" if field else key
                    errors.append(f"{path}: {err['msg']}")

        if errors:
            raise ValueError("; ".join(errors))

        return result


class AppEmbeddingFields(BaseModel):
    """
    Fields used to generate app embedding.
    """

    name: str
    display_name: str
    provider: str
    description: str
    categories: list[str]


class AppsSearch(BaseModel):
    """
    Parameters for searching applications.
    TODO: category enum?
    TODO: filter by similarity score?
    """

    intent: str | None = Field(
        default=None,
        description="Natural language intent for vector similarity sorting. Results will be sorted by relevance to the intent.",
    )
    allowed_apps_only: bool = Field(
        default=False,
        description="If true, only return apps that are allowed by the agent/accessor, identified by the api key.",
    )
    include_functions: bool = Field(
        default=False,
        description="If true, include functions (name and description) of each app in the response.",
    )
    categories: list[str] | None = Field(
        default=None, description="List of categories for filtering."
    )
    limit: int = Field(
        default=100, ge=1, le=1000, description="Maximum number of Apps per response."
    )
    offset: int = Field(default=0, ge=0, description="Pagination offset.")

    # need this in case user set {"categories": None} which will translate to [''] in the params
    @field_validator("categories")
    def validate_categories(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            # Remove any empty strings from the list
            v = [category for category in v if category.strip()]
            # If after removing empty strings the list is empty, set it to None
            if not v:
                return None
        return v

    # empty intent or string with spaces should be treated as None
    @field_validator("intent")
    def validate_intent(cls, v: str | None) -> str | None:
        if v is not None and v.strip() == "":
            return None
        return v


class AppsList(BaseModel):
    """
    Parameters for listing Apps.
    """

    app_names: list[str] | None = Field(default=None, description="List of app names to filter by.")
    limit: int = Field(
        default=100, ge=1, le=1000, description="Maximum number of Apps per response."
    )
    offset: int = Field(default=0, ge=0, description="Pagination offset.")


class AppBasic(BaseModel):
    name: str
    description: str
    functions: list[BasicFunctionDefinition] | None = None

    model_config = ConfigDict(from_attributes=True)


class AppDetails(BaseModel):
    id: UUID
    name: str
    display_name: str
    provider: str
    version: str
    description: str
    logo: str | None
    categories: list[str]
    visibility: Visibility
    active: bool
    # Note this field is different from security_schemes in the db model. Here it's just a list of supported SecurityScheme.
    # the security_schemes field in the db model is a dict of supported security schemes and their config,
    # which contains sensitive information like OAuth2 client secret.
    security_schemes: list[SecurityScheme]
    # TODO: added supported_security_schemes instead of chaning security_schemes for backward compatibility
    # consider merging the two fields in the future
    supported_security_schemes: SecuritySchemesPublic

    functions: list[FunctionDetails]

    created_at: datetime
    updated_at: datetime

    custom_app: bool


class AppSecuritySchemeLocations(BaseModel):
    """
    Credential-placement metadata (header/query/body location, name, prefix) for an app's
    supported security schemes. Deliberately separate from AppDetails.supported_security_schemes,
    which strips this out — a client that already holds a linked account's real secret needs this
    to know where to place it in a request, without changing AppDetails' existing contract.
    """

    app_name: str
    security_scheme_locations: SecuritySchemesLocations
