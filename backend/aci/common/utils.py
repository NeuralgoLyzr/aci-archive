import json
import os
import re
import secrets
from functools import cache
from uuid import UUID

import aioboto3
import boto3
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from aci.common.logging_setup import get_logger

logger = get_logger(__name__)


def check_and_get_env_variable(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        raise ValueError(f"Environment variable '{name}' is not set")
    if value == "":
        raise ValueError(f"Environment variable '{name}' is empty string")
    return value


def is_enterprise_deployment() -> bool:
    """Master switch for the on-prem/self-hosted env-var-optionality behavior.

    Defaults to false, which preserves the original hard-required behavior
    (check_and_get_env_variable raises at import for unset vars). Set
    IS_ENTERPRISE_DEPLOYMENT=true to allow the server to start without every
    integration configured.
    """
    return os.getenv("IS_ENTERPRISE_DEPLOYMENT", "false").strip().lower() == "true"


def get_env_variable(name: str, default: str | None = None) -> str | None:
    """Like `check_and_get_env_variable`, but tolerant of unset vars when
    on-prem mode is enabled.

    Used for on-prem/self-hosted deployments where not every integration
    (billing, observability, third-party auth, ...) is configured — the
    app should start and only fail when the corresponding feature is
    actually exercised, not at import time. When IS_ENTERPRISE_DEPLOYMENT isn't
    set to "true", this behaves exactly like `check_and_get_env_variable`.
    """
    if not is_enterprise_deployment():
        return check_and_get_env_variable(name)

    value = os.getenv(name)
    return value if value else default


def get_lyzr_api_key_id() -> UUID | None:
    """Returns LYZR_API_KEY_ID_DB (the platform-seeded apps' api_key_id) as a
    UUID, or None when unset.

    Callers previously did `UUID(os.getenv("LYZR_API_KEY_ID_DB"))` inline,
    which raises TypeError at import/request time whenever the var is unset
    (e.g. on-prem deployments that never seeded with a platform key). With
    None, SQLAlchemy filters degrade to `api_key_id IS NULL`, which matches
    apps seeded without a platform key.
    """
    value = os.getenv("LYZR_API_KEY_ID_DB")
    return UUID(value) if value else None


def get_or_generate_secret(name: str, default: str | None = None) -> str:
    """Returns the env var, `default` if given, or a random ephemeral secret.

    For values used as cryptographic secrets (signing keys, hashing secrets)
    that have no safe hardcoded default. In on-prem mode, an ephemeral secret
    lets the app start without configuration, but it changes on every
    restart — sessions and previously hashed values won't survive a restart.
    Logs a warning so this doesn't fail silently. When IS_ENTERPRISE_DEPLOYMENT
    isn't set to "true", this behaves exactly like `check_and_get_env_variable`.
    """
    if not is_enterprise_deployment():
        return check_and_get_env_variable(name)

    value = os.getenv(name) or default
    if value:
        return value

    generated = secrets.token_urlsafe(32)
    logger.warning(
        f"Environment variable '{name}' is not set — generated an ephemeral secret for this "
        "process. It will change on every restart, invalidating existing sessions/hashes. "
        f"Set '{name}' explicitly for production deployments."
    )
    return generated


_db_url_cache: str | None = None


def get_db_password_sync() -> str:
    """Returns the DB password.

    On-prem mode: from SERVER_DB_PASSWORD directly, or from AWS Secrets
    Manager. Otherwise (original behavior): from SERVER_DB_PASSWORD only on
    Azure, or from AWS Secrets Manager (DB_SECRET_NAME/AWS_REGION_NAME
    required) everywhere else.
    """
    if is_enterprise_deployment():
        direct_password = os.getenv("SERVER_DB_PASSWORD")
        if direct_password:
            return direct_password

        secret_name = os.getenv("DB_SECRET_NAME")
        region_name = os.getenv("AWS_REGION_NAME")
        if not secret_name or not region_name:
            raise RuntimeError(
                "No DB password configured: set SERVER_DB_PASSWORD directly, or both "
                "DB_SECRET_NAME and AWS_REGION_NAME to fetch it from AWS Secrets Manager."
            )
    else:
        if os.getenv("CLOUD_PLATFORM") == "azure":
            return check_and_get_env_variable("SERVER_DB_PASSWORD")

        secret_name = check_and_get_env_variable("DB_SECRET_NAME")
        region_name = check_and_get_env_variable("AWS_REGION_NAME")

    client = boto3.client("secretsmanager", region_name=region_name)
    response = client.get_secret_value(SecretId=secret_name)
    secret_dict = json.loads(response["SecretString"])
    return secret_dict["password"]


async def get_db_password() -> str:
    """Returns the DB password.

    On-prem mode: from SERVER_DB_PASSWORD directly, or from AWS Secrets
    Manager. Otherwise (original behavior): from SERVER_DB_PASSWORD only on
    Azure, or from AWS Secrets Manager (DB_SECRET_NAME/AWS_REGION_NAME
    required) everywhere else.
    """
    if is_enterprise_deployment():
        direct_password = os.getenv("SERVER_DB_PASSWORD")
        if direct_password:
            return direct_password

        secret_name = os.getenv("DB_SECRET_NAME")
        region_name = os.getenv("AWS_REGION_NAME")
        if not secret_name or not region_name:
            raise RuntimeError(
                "No DB password configured: set SERVER_DB_PASSWORD directly, or both "
                "DB_SECRET_NAME and AWS_REGION_NAME to fetch it from AWS Secrets Manager."
            )
    else:
        if os.getenv("CLOUD_PLATFORM") == "azure":
            return check_and_get_env_variable("SERVER_DB_PASSWORD")

        secret_name = check_and_get_env_variable("DB_SECRET_NAME")
        region_name = check_and_get_env_variable("AWS_REGION_NAME")

    async with aioboto3.Session(region_name=region_name).client("secretsmanager") as client:
        response = await client.get_secret_value(SecretId=secret_name)
        secret_dict = json.loads(response["SecretString"])
        return secret_dict["password"]


def construct_db_url_sync(
    scheme: str, user: str, host: str, port: str, db_name: str
) -> str:
    """
    Constructs the database URL by fetching the password from AWS Secrets Manager synchronously.
    The result is cached to avoid repeated API calls.
    """
    global _db_url_cache
    if _db_url_cache is not None:
        return _db_url_cache

    password = get_db_password_sync()
    _db_url_cache = f"{scheme}://{user}:{password}@{host}:{port}/{db_name}"
    return _db_url_cache


async def construct_db_url(
    scheme: str, user: str, host: str, port: str, db_name: str
) -> str:
    """
    Constructs the database URL by fetching the password from AWS Secrets Manager asynchronously.
    The result is cached to avoid repeated API calls.
    """
    global _db_url_cache
    if _db_url_cache is not None:
        return _db_url_cache

    password = await get_db_password()
    _db_url_cache = f"{scheme}://{user}:{password}@{host}:{port}/{db_name}"
    return _db_url_cache


def format_to_screaming_snake_case(name: str) -> str:
    """
    Convert a string with spaces, hyphens, slashes, camel case etc. to screaming snake case.
    e.g., "GitHub Create Repository" -> "GITHUB_CREATE_REPOSITORY"
    e.g., "GitHub/Create Repository" -> "GITHUB_CREATE_REPOSITORY"
    e.g., "github-create-repository" -> "GITHUB_CREATE_REPOSITORY"
    """
    name = re.sub(r"[\W]+", "_", name)  # Replace non-alphanumeric characters with underscore
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
    s3 = s2.replace("-", "_").replace("/", "_").replace(" ", "_")
    s3 = re.sub("_+", "_", s3)  # Replace multiple underscores with single underscore
    s4 = s3.upper().strip("_")

    return s4


# NOTE: it's important that you don't create a new engine for each session, which takes
# up db resources and will lead up to errors pretty fast
# TODO: fine tune the pool settings
@cache
def get_db_engine(db_url: str) -> Engine:
    return create_engine(
        db_url,
        pool_size=10,
        max_overflow=10,
        pool_timeout=30,
        pool_recycle=3600,  # recycle connections after 1 hour
        pool_pre_ping=True,
    )


# NOTE: cache this because only one sessionmaker is needed for all db sessions
@cache
def get_sessionmaker(db_url: str) -> sessionmaker:
    engine = get_db_engine(db_url)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_db_session(db_url: str) -> Session:
    SessionMaker = get_sessionmaker(db_url)
    session: Session = SessionMaker()

    return session


def parse_app_name_from_function_name(function_name: str) -> str:
    """
    Parse the app name from a function name.
    e.g., "ACI_TEST__HELLO_WORLD" -> "ACI_TEST"
    """
    return function_name.split("__")[0]


def snake_to_camel(string: str) -> str:
    """
    Convert a snake case string to a camel case string.
    e.g., "snake_case_string" -> "SnakeCaseString"
    """
    parts = string.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


def is_uuid(value: str | UUID) -> bool:
    if isinstance(value, UUID):
        return True
    try:
        UUID(value)
        return True
    except ValueError:
        return False
