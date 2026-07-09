import os
from aci.common.utils import (
    construct_db_url,
    construct_db_url_sync,
    get_env_variable,
    get_or_generate_secret,
)

# Defaults to "production" (the safest assumption) rather than "local", so
# behavior meant only for local dev isn't silently enabled when unset.
ENVIRONMENT = get_env_variable("SERVER_ENVIRONMENT", "production")

# LLM — optional; several modules construct an OpenAI client at import time,
# so this falls back to a placeholder (rather than None) to avoid crashing
# the whole app on import. Actual OpenAI-backed features will fail with a
# clear auth error only when invoked without a real key configured.
OPENAI_API_KEY = get_env_variable("SERVER_OPENAI_API_KEY", "not-configured")
OPENAI_EMBEDDING_MODEL = get_env_variable("SERVER_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OPENAI_EMBEDDING_DIMENSION = int(get_env_variable("SERVER_OPENAI_EMBEDDING_DIMENSION", "1536"))

# JWT
SIGNING_KEY = get_or_generate_secret("SERVER_SIGNING_KEY")
JWT_ALGORITHM = get_env_variable("SERVER_JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    get_env_variable("SERVER_JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
)
REDIRECT_URI_BASE = get_env_variable("SERVER_REDIRECT_URI_BASE")
COOKIE_KEY_FOR_AUTH_TOKEN = "accessToken"

# Google Auth
GOOGLE_AUTH_CLIENT_SCOPE = "openid email profile"

# DB connection settings — default to the local docker-compose values so the
# app still boots without an explicit .env; real deployments override these.
DB_SCHEME = get_env_variable("SERVER_DB_SCHEME", "postgresql+psycopg")
DB_USER = get_env_variable("SERVER_DB_USER", "user")
DB_HOST = get_env_variable("SERVER_DB_HOST", "db")
DB_PORT = get_env_variable("SERVER_DB_PORT", "5432")
DB_NAME = get_env_variable("SERVER_DB_NAME", "local_db")

# DB_FULL_URL will be initialized asynchronously by calling get_db_full_url()
DB_FULL_URL: str | None = None


def get_db_full_url_sync() -> str:
    """
    Lazily initializes and returns the database URL synchronously.
    Fetches password from AWS Secrets Manager on first call.
    """
    global DB_FULL_URL
    if DB_FULL_URL is not None:
        return DB_FULL_URL

    DB_FULL_URL = construct_db_url_sync(DB_SCHEME, DB_USER, DB_HOST, DB_PORT, DB_NAME)
    return DB_FULL_URL


async def get_db_full_url() -> str:
    """
    Lazily initializes and returns the database URL asynchronously.
    Fetches password from AWS Secrets Manager on first call.
    """
    global DB_FULL_URL
    if DB_FULL_URL is not None:
        return DB_FULL_URL

    DB_FULL_URL = await construct_db_url(DB_SCHEME, DB_USER, DB_HOST, DB_PORT, DB_NAME)
    return DB_FULL_URL

# PropelAuth — optional; auth routes relying on it will error clearly if unset.
PROPELAUTH_AUTH_URL = get_env_variable("SERVER_PROPELAUTH_AUTH_URL")
PROPELAUTH_API_KEY = get_env_variable("SERVER_PROPELAUTH_API_KEY")

# SVIX — optional; webhook signing/verification will error clearly if unset.
SVIX_SIGNING_SECRET = get_env_variable("SERVER_SVIX_SIGNING_SECRET")

# RATE LIMITS
RATE_LIMIT_IP_PER_SECOND = int(get_env_variable("SERVER_RATE_LIMIT_IP_PER_SECOND", "100"))
RATE_LIMIT_IP_PER_DAY = int(get_env_variable("SERVER_RATE_LIMIT_IP_PER_DAY", "100000"))

# QUOTA
PROJECT_DAILY_QUOTA = int(get_env_variable("SERVER_PROJECT_DAILY_QUOTA", "100000"))
MAX_AGENTS_PER_PROJECT = int(get_env_variable("SERVER_MAX_AGENTS_PER_PROJECT", "10"))
# Trusted upstream proxy IPs/hostnames/CIDRs for ProxyHeadersMiddleware.
# Accepts a comma-separated list of exact IPs, hostnames, or CIDR ranges.
# AWS ALB:          set to the ALB DNS name or IP
# Azure App GW:     set to the App Gateway subnet CIDR (e.g. "10.200.0.0/24")
# Falls back to the legacy SERVER_APPLICATION_LOAD_BALANCER_DNS var if set.
# Defaults to "*" (trust all) when unset — safe behind a private-subnet proxy.
TRUSTED_PROXY_HOSTS: str = (
    os.getenv("SERVER_TRUSTED_PROXY_HOSTS")
    or os.getenv("SERVER_APPLICATION_LOAD_BALANCER_DNS")
    or "*"
)
OAUTH2_CLIENT_CREDENTIALS_FALLBACK_TTL_SECONDS = int(
    get_env_variable("CLIENT_CREDENTIALS_FALLBACK_TTL_SECONDS", "300")
)

# APP
APP_TITLE = "ACI"
APP_VERSION = "0.0.1-beta.4"
APP_DOCS_URL = "/v1/notforhuman-docs"
APP_REDOC_URL = "/v1/notforhuman-redoc"
APP_OPENAPI_URL = "/v1/notforhuman-openapi.json"

# ROUTERS
ROUTER_PREFIX_HEALTH = "/v1/health"
ROUTER_PREFIX_AUTH = "/v1/auth"
ROUTER_PREFIX_PROJECTS = "/v1/projects"
ROUTER_PREFIX_APPS = "/v1/apps"
ROUTER_PREFIX_FUNCTIONS = "/v1/functions"
ROUTER_PREFIX_APP_CONFIGURATIONS = "/v1/app-configurations"
ROUTER_PREFIX_LINKED_ACCOUNTS = "/v1/linked-accounts"
ROUTER_PREFIX_AGENT = "/v1/agent"
ROUTER_PREFIX_ANALYTICS = "/v1/analytics"
ROUTER_PREFIX_WEBHOOKS = "/v1/webhooks"
ROUTER_PREFIX_BILLING = "/v1/billing"
ROUTER_PREFIX_ORGANIZATIONS = "/v1/organizations"
ROUTER_PREFIX_DOCS = "/v1/docs"
ROUTER_PREFIX_TOOL_SEEDING = "/v1/tool-seeding"
ROUTER_PREFIX_SEEDING_INFO = "/v1/seeding-info"

# DEV PORTAL
DEV_PORTAL_URL = get_env_variable("SERVER_DEV_PORTAL_URL")

# LOGFIRE — optional; observability is skipped when unset (see main.py).
LOGFIRE_WRITE_TOKEN = get_env_variable("SERVER_LOGFIRE_WRITE_TOKEN")
LOGFIRE_READ_TOKEN = get_env_variable("SERVER_LOGFIRE_READ_TOKEN")

# STRIPE — optional; billing routes relying on it will error clearly if unset.
STRIPE_SECRET_KEY = get_env_variable("SERVER_STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SIGNING_SECRET = get_env_variable("SERVER_STRIPE_WEBHOOK_SIGNING_SECRET")

# HEADERS
ACI_ORG_ID_HEADER = "X-ACI-ORG-ID"
ACI_API_KEY_HEADER = "X-API-KEY"

# 8KB
MAX_LOG_FIELD_SIZE = 8 * 1024

# Agentic Apps — optional; the frontend QA agent feature is skipped without it.
ANTHROPIC_API_KEY = get_env_variable("SERVER_ANTHROPIC_API_KEY")
ANTHROPIC_MODEL_FOR_FRONTEND_QA_AGENT = "claude-3-5-sonnet-latest"

# Vector DB — optional; docs search is skipped without it.
VECTOR_DB_FULL_URL = get_env_variable("SERVER_VECTOR_DB_FULL_URL")
