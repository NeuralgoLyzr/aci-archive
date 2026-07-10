import os

from dotenv import load_dotenv

from aci.common.utils import construct_db_url, construct_db_url_sync, get_env_variable

load_dotenv()

# When IS_ENTERPRISE_DEPLOYMENT=true these fall back to the SERVER_* values
# (the server imports this module via the tool-seeding routes, and seeding
# must target the same DB/embedding config as the server) and finally to
# safe defaults, so the server can start without any CLI_* vars set.
# Otherwise (cloud/CLI usage) every CLI_* var is hard-required, as before.
OPENAI_API_KEY = get_env_variable(
    "CLI_OPENAI_API_KEY", os.getenv("SERVER_OPENAI_API_KEY") or "not-configured"
)
OPENAI_EMBEDDING_MODEL = get_env_variable(
    "CLI_OPENAI_EMBEDDING_MODEL",
    os.getenv("SERVER_OPENAI_EMBEDDING_MODEL") or "text-embedding-3-small",
)
OPENAI_EMBEDDING_DIMENSION = int(
    get_env_variable(
        "CLI_OPENAI_EMBEDDING_DIMENSION",
        os.getenv("SERVER_OPENAI_EMBEDDING_DIMENSION") or "1536",
    )
)
DB_SCHEME = get_env_variable("CLI_DB_SCHEME", os.getenv("SERVER_DB_SCHEME") or "postgresql+psycopg")
DB_USER = get_env_variable("CLI_DB_USER", os.getenv("SERVER_DB_USER") or "user")
DB_HOST = get_env_variable("CLI_DB_HOST", os.getenv("SERVER_DB_HOST") or "db")
DB_PORT = get_env_variable("CLI_DB_PORT", os.getenv("SERVER_DB_PORT") or "5432")
DB_NAME = get_env_variable("CLI_DB_NAME", os.getenv("SERVER_DB_NAME") or "local_db")
SERVER_URL = get_env_variable("CLI_SERVER_URL", "http://localhost:8000")

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
