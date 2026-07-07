import asyncio
import os
import re
from functools import cache
from uuid import UUID

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


_db_url_cache: str | None = None
_secrets_backend = None


def _get_secrets_backend():
    """Build a cloudrift secrets backend based on CLOUD_PLATFORM."""
    global _secrets_backend
    if _secrets_backend is not None:
        return _secrets_backend

    from cloudrift.secrets import get_secrets

    cloud_platform = os.getenv("CLOUD_PLATFORM", "aws")
    if cloud_platform == "azure":
        vault_url = check_and_get_env_variable("AZURE_KEY_VAULT_URL")
        _secrets_backend = get_secrets("azure_keyvault", vault_url=vault_url)
    else:
        region = check_and_get_env_variable("AWS_REGION_NAME")
        kwargs: dict = {"region": region}
        ak = os.getenv("AWS_ACCESS_KEY_ID")
        sk = os.getenv("AWS_SECRET_ACCESS_KEY")
        if ak and sk:
            kwargs["aws_access_key_id"] = ak
            kwargs["aws_secret_access_key"] = sk
        _secrets_backend = get_secrets("aws_secrets_manager", **kwargs)
    return _secrets_backend


async def _fetch_db_password(secret_name: str) -> str:
    """Fetch DB password from cloudrift secrets backend."""
    backend = _get_secrets_backend()
    cloud_platform = os.getenv("CLOUD_PLATFORM", "aws")
    if cloud_platform == "azure":
        return await backend.get_secret(secret_name)
    secret_dict = await backend.get_secret_json(secret_name)
    return secret_dict["password"]


def get_db_password_sync() -> str:
    """Returns the DB password via cloudrift secrets (sync wrapper)."""
    secret_name = os.getenv("DB_SECRET_NAME")
    if not secret_name:
        return os.getenv("SERVER_DB_PASSWORD", "")
    return asyncio.run(_fetch_db_password(secret_name))


async def get_db_password() -> str:
    """Returns the DB password via cloudrift secrets (async)."""
    secret_name = os.getenv("DB_SECRET_NAME")
    if not secret_name:
        return os.getenv("SERVER_DB_PASSWORD", "")
    return await _fetch_db_password(secret_name)


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
