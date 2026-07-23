from dotenv import load_dotenv

from aci.common.utils import check_and_get_env_variable, construct_db_url, construct_db_url_sync

load_dotenv()

OPENAI_API_KEY = check_and_get_env_variable("CLI_OPENAI_API_KEY")
OPENAI_EMBEDDING_MODEL = check_and_get_env_variable("CLI_OPENAI_EMBEDDING_MODEL")
OPENAI_EMBEDDING_DIMENSION = int(check_and_get_env_variable("CLI_OPENAI_EMBEDDING_DIMENSION"))
DB_SCHEME = check_and_get_env_variable("CLI_DB_SCHEME")
DB_USER = check_and_get_env_variable("CLI_DB_USER")
DB_HOST = check_and_get_env_variable("CLI_DB_HOST")
DB_PORT = check_and_get_env_variable("CLI_DB_PORT")
DB_NAME = check_and_get_env_variable("CLI_DB_NAME")
SERVER_URL = check_and_get_env_variable("CLI_SERVER_URL")

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
