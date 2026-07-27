from typing import Annotated
from fastapi import APIRouter, Depends, Query
from openai import OpenAI

from aci.common.db import crud
from aci.common.embeddings import generate_embedding
from aci.common.enums import Visibility
from aci.common.exceptions import AppNotFound
from aci.common.logging_setup import get_logger
from aci.common.schemas.app import (
    AppBasic,
    AppDetails,
    AppSecuritySchemeLocations,
    AppsList,
    AppsSearch,
)
from aci.common.schemas.function import BasicFunctionDefinition, FunctionDetails
from aci.common.schemas.security_scheme import SecuritySchemesLocations, SecuritySchemesPublic
from aci.common.utils import get_lyzr_api_key_id
from aci.server import config
from aci.server import dependencies as deps

logger = get_logger(__name__)
router = APIRouter()
# TODO: will this be a bottleneck and problem if high concurrent requests from users?
openai_client = OpenAI(api_key=config.OPENAI_API_KEY)
LYZR_API_KEY_ID_DB = get_lyzr_api_key_id()


@router.get("", response_model_exclude_none=True)
async def list_apps(
    context: Annotated[deps.RequestContext, Depends(deps.get_request_context)],
    query_params: Annotated[AppsList, Query()],
) -> list[AppDetails]:
    """
    Get a list of Apps and their details. Sorted by App name.
    """
    apps = crud.apps.get_apps(
        context.db_session,
        context.project.visibility_access == Visibility.PUBLIC,
        True,
        query_params.app_names,
        query_params.limit,
        query_params.offset,
        api_key_id=context.api_key_id,
    )

    # TODO: Now if include_functions=true, it returns all functions of the app whether or not it is enabled by the agent.
    # We can either add a optional filtering logic or add a flag to clarify whether each function is enabled by the agent.
    response: list[AppDetails] = []
    for app in apps:
        app_details = AppDetails(
            id=app.id,
            name=app.name,
            display_name=app.display_name,
            provider=app.provider,
            version=app.version,
            description=app.description,
            logo=app.logo,
            categories=app.categories,
            visibility=app.visibility,
            active=app.active,
            security_schemes=list(app.security_schemes.keys()),
            # TODO: check validation latency
            supported_security_schemes=SecuritySchemesPublic.model_validate(app.security_schemes),
            functions=[FunctionDetails.model_validate(function) for function in app.functions],
            created_at=app.created_at,
            updated_at=app.updated_at,
            custom_app=app.api_key_id != LYZR_API_KEY_ID_DB,
        )
        response.append(app_details)

    return response


@router.get("/security-scheme-locations", response_model=list[AppSecuritySchemeLocations])
async def list_app_security_scheme_locations(
    context: Annotated[deps.RequestContext, Depends(deps.get_request_context)],
    query_params: Annotated[AppsList, Query()],
) -> list[AppSecuritySchemeLocations]:
    """
    Get credential-placement metadata (header/query/body location, name, prefix) for each app's
    supported security schemes.

    Deliberately separate from GET /v1/apps and GET /v1/apps/{app_name}, whose
    supported_security_schemes strips this out — a client that already holds a linked account's
    real secret (e.g. via GET /v1/linked-accounts/{id}/credentials) needs this to know where to
    place it in an outbound request. Zero change to those existing routes' responses.

    Note: registered ahead of GET /{app_name} below so "security-scheme-locations" is never
    matched as an app_name path parameter.
    """
    apps = crud.apps.get_apps(
        context.db_session,
        context.project.visibility_access == Visibility.PUBLIC,
        True,
        query_params.app_names,
        query_params.limit,
        query_params.offset,
        api_key_id=context.api_key_id,
    )
    return [
        AppSecuritySchemeLocations(
            app_name=app.name,
            security_scheme_locations=SecuritySchemesLocations.model_validate(app.security_schemes),
        )
        for app in apps
    ]


@router.get("/search", response_model_exclude_none=True)
async def search_apps(
    context: Annotated[deps.RequestContext, Depends(deps.get_request_context)],
    query_params: Annotated[AppsSearch, Query()],
) -> list[AppBasic]:
    """
    Search for Apps.
    Intented to be used by agents to search for apps based on natural language intent.
    """
    # TODO: currently the search is done across all apps, we might want to add flags to account for below scenarios:
    # - when clients search for apps, if an app is configured but disabled by client, should it be discoverable?

    # TODO: Now if include_functions=true, it returns all functions of the app whether or not it is enabled by the agent.
    # We can either add a optional filtering logic or add a flag to clarify whether each function is enabled by the agent.

    intent_embedding = (
        generate_embedding(
            openai_client,
            config.OPENAI_EMBEDDING_MODEL,
            config.OPENAI_EMBEDDING_DIMENSION,
            query_params.intent,
        )
        if query_params.intent
        else None
    )
    logger.debug(
        f"Generated intent embedding, intent={query_params.intent}, intent_embedding={intent_embedding}"
    )
    # if the search is restricted to allowed apps, we need to filter the apps by the agent's allowed apps.
    # None means no filtering
    apps_to_filter = context.agent.allowed_apps if query_params.allowed_apps_only else None

    apps_with_scores = crud.apps.search_apps(
        context.db_session,
        context.project.visibility_access == Visibility.PUBLIC,
        True,
        apps_to_filter,
        query_params.categories,
        intent_embedding,
        query_params.limit,
        query_params.offset,
    )

    apps: list[AppBasic] = []

    for app, _ in apps_with_scores:
        if query_params.include_functions:
            functions = [
                BasicFunctionDefinition(name=function.name, description=function.description)
                for function in app.functions
            ]
            apps.append(AppBasic(name=app.name, description=app.description, functions=functions))
        else:
            apps.append(AppBasic(name=app.name, description=app.description))

    logger.info(
        "Search apps result",
        extra={
            "search_apps": {
                "query_params_json": query_params.model_dump_json(),
                "app_names": [app.name for app, _ in apps_with_scores],
            },
        },
    )

    return apps


@router.get("/{app_name}", response_model_exclude_none=True)
async def get_app_details(
    context: Annotated[deps.RequestContext, Depends(deps.get_request_context)],
    app_name: str,
) -> AppDetails:
    """
    Returns an application (name, description, and functions).
    """
    app = crud.apps.get_app(
        context.db_session,
        app_name,
        context.project.visibility_access == Visibility.PUBLIC,
        True,
    )

    if not app:
        logger.error(f"App not found, app_name={app_name}")

        raise AppNotFound(f"App={app_name} not found")

    # filter functions by project visibility and active status
    # TODO: better way and place for crud filtering/acl logic like this?
    functions = [
        function
        for function in app.functions
        if function.active
        and not (
            context.project.visibility_access == Visibility.PUBLIC
            and function.visibility != Visibility.PUBLIC
        )
    ]

    app_details: AppDetails = AppDetails(
        id=app.id,
        name=app.name,
        display_name=app.display_name,
        provider=app.provider,
        version=app.version,
        description=app.description,
        logo=app.logo,
        categories=app.categories,
        visibility=app.visibility,
        active=app.active,
        security_schemes=list(app.security_schemes.keys()),
        supported_security_schemes=SecuritySchemesPublic.model_validate(app.security_schemes),
        functions=[FunctionDetails.model_validate(function) for function in functions],
        created_at=app.created_at,
        updated_at=app.updated_at,
        custom_app=app.api_key_id != LYZR_API_KEY_ID_DB,
    )

    return app_details
