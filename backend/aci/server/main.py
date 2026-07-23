from typing import Any

import logfire
import stripe
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pythonjsonlogger.json import JsonFormatter
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from aci.common.exceptions import ACIException
from aci.common.logging_setup import setup_logging
from aci.server import config
from aci.server import dependencies as deps
from aci.server.acl import get_propelauth
from aci.server.dependency_check import check_dependencies
from aci.server.fix_schema import fix_schema
from aci.server.log_schema_filter import LogSchemaFilter
from aci.server.middleware.interceptor import InterceptorMiddleware, RequestContextFilter
from aci.server.middleware.ratelimit import RateLimitMiddleware
from aci.server.routes import (
    agent,
    analytics,
    app_configurations,
    apps,
    billing,
    docs,
    functions,
    health,
    linked_accounts,
    organizations,
    projects,
    tool_seeding,
    webhooks,
)
from aci.server.fix_schema import fix_schema
from aci.server.sentry import setup_sentry

# Run simple schema fixes first (if RUN_SCHEMA_FIXES=true)
fix_schema()

check_dependencies()

# Run schema fixes
fix_schema()

setup_sentry()

# Lambda-based seeding will run in background after server starts

setup_logging(
    formatter=JsonFormatter(
        "{levelname} {asctime} {name} {message}",
        style="{",
        rename_fields={"asctime": "timestamp", "name": "file", "levelname": "level"},
    ),
    filters=[RequestContextFilter(), LogSchemaFilter()],
    environment=config.ENVIRONMENT,
)

stripe.api_key = config.STRIPE_SECRET_KEY


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


# TODO: move to config
app = FastAPI(
    title=config.APP_TITLE,
    version=config.APP_VERSION,
    docs_url=config.APP_DOCS_URL,
    redoc_url=config.APP_REDOC_URL,
    openapi_url=config.APP_OPENAPI_URL,
    generate_unique_id_function=custom_generate_unique_id,
)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize database connection on server startup."""
    await config.get_db_full_url()
    logger.info("Database URL initialized")


auth = get_propelauth()


# No auto-seeding - manual seeding only
import logging
logger = logging.getLogger(__name__)
logger.info("Skipping auto-seeding - manual seeding required")


def scrubbing_callback(m: logfire.ScrubMatch) -> Any:
    if m.path == ("attributes", "api_key_id"):
        return m.value


# Skip logfire in production if no valid token
if config.ENVIRONMENT != "local" and config.LOGFIRE_WRITE_TOKEN and config.LOGFIRE_WRITE_TOKEN != "dummy":
    try:
        logfire.configure(
            console=False,
            token=config.LOGFIRE_WRITE_TOKEN,
            environment=config.ENVIRONMENT,
            scrubbing=logfire.ScrubbingOptions(callback=scrubbing_callback),
        )
        logfire.instrument_fastapi(app, capture_headers=True)
        logfire.instrument_sqlalchemy()
    except Exception as e:
        logger.warning(f"Failed to configure logfire: {e}")
else:
    logger.info("Skipping logfire configuration - no valid token provided")

"""middlewares are executed in the reverse order"""
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SessionMiddleware, secret_key=config.SIGNING_KEY)
# TODO: for now, we don't use TrustedHostMiddleware because it blocks health check from AWS ALB:
# When ALB send health check request, it uses the task IP as the host, instead of the DNS name.
# ALB health check headers example: Headers({'host': '10.0.164.143:8000', 'user-agent': 'ELB-HealthChecker/2.0'})
# where 10.0.164.143 is the the host IP of the fargate task, in which case TrustedHostMiddleware will block the request.
# It should be fine to remove TrustedHostMiddleware as we are running the service in a private subnet behind ALB with WAF integration.
# app.add_middleware(
#     TrustedHostMiddleware,
#     allowed_hosts=[
#         "localhost",
#         "127.0.0.1",
#         config.ACI_DNS,
#     ],
# )
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://main.de73cci4api6i.amplifyapp.com",
        "https://aci.studio.lyzr.ai",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(InterceptorMiddleware)
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=[config.APPLICATION_LOAD_BALANCER_DNS])


# NOTE: generic exception handler (type Exception) for all exceptions doesn't work
# https://github.com/fastapi/fastapi/discussions/9478
# That's why we have another catch-all in the interceptor middleware
@app.exception_handler(ACIException)
async def global_exception_handler(request: Request, exc: ACIException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.error_code,
        content={"error": f"{exc.title}, {exc.message}" if exc.message else exc.title},
    )


# TODO: custom rate limiting on different routes
app.include_router(
    health.router,
    prefix=config.ROUTER_PREFIX_HEALTH,
    tags=[config.ROUTER_PREFIX_HEALTH.split("/")[-1]],
)

app.include_router(
    projects.router,
    prefix=config.ROUTER_PREFIX_PROJECTS,
    tags=[config.ROUTER_PREFIX_PROJECTS.split("/")[-1]],
    # dependencies=[Depends(auth.require_user)],
)
# TODO: add get_project to all routes
app.include_router(
    apps.router,
    prefix=config.ROUTER_PREFIX_APPS,
    tags=[config.ROUTER_PREFIX_APPS.split("/")[-1]],
    dependencies=[Depends(deps.validate_api_key), Depends(deps.get_project)],
)
app.include_router(
    functions.router,
    prefix=config.ROUTER_PREFIX_FUNCTIONS,
    tags=[config.ROUTER_PREFIX_FUNCTIONS.split("/")[-1]],
    dependencies=[Depends(deps.validate_api_key), Depends(deps.get_project)],
)
app.include_router(
    app_configurations.router,
    prefix=config.ROUTER_PREFIX_APP_CONFIGURATIONS,
    tags=[config.ROUTER_PREFIX_APP_CONFIGURATIONS.split("/")[-1]],
    dependencies=[Depends(deps.validate_api_key)],
)
# similar to auth, it contains a callback route so can't use global dependencies here
app.include_router(
    linked_accounts.router,
    prefix=config.ROUTER_PREFIX_LINKED_ACCOUNTS,
    tags=[config.ROUTER_PREFIX_LINKED_ACCOUNTS.split("/")[-1]],
)

app.include_router(
    agent.router,
    prefix=config.ROUTER_PREFIX_AGENT,
    tags=[config.ROUTER_PREFIX_AGENT.split("/")[-1]],
)

app.include_router(
    analytics.router,
    prefix=config.ROUTER_PREFIX_ANALYTICS,
    tags=[config.ROUTER_PREFIX_ANALYTICS.split("/")[-1]],
)

app.include_router(
    webhooks.router,
    prefix=config.ROUTER_PREFIX_WEBHOOKS,
    tags=[config.ROUTER_PREFIX_WEBHOOKS.split("/")[-1]],
)

app.include_router(
    billing.router,
    prefix=config.ROUTER_PREFIX_BILLING,
    tags=[config.ROUTER_PREFIX_BILLING.split("/")[-1]],
)

app.include_router(
    organizations.router,
    prefix=config.ROUTER_PREFIX_ORGANIZATIONS,
    tags=[config.ROUTER_PREFIX_ORGANIZATIONS.split("/")[-1]],
)

app.include_router(
    docs.router,
    prefix=config.ROUTER_PREFIX_DOCS,
    tags=[config.ROUTER_PREFIX_DOCS.split("/")[-1]],
)

app.include_router(
    tool_seeding.router,
    prefix="/v1/tool-seeding",
    tags=["tool-seeding"],
    # dependencies=[Depends(auth.require_user)],  # Enable PropelAuth authentication
)
