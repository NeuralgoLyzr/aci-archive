from uuid import UUID

from sqlalchemy import select, update, or_
from sqlalchemy.orm import Session

from aci.common import utils
from aci.common.utils import get_lyzr_api_key_id
from aci.common.db import crud
from aci.common.db.sql_models import App, Function
from aci.common.enums import Visibility
from aci.common.logging_setup import get_logger
from aci.common.schemas.function import FunctionUpsert

logger = get_logger(__name__)


def create_functions(
    db_session: Session,
    functions_upsert: list[FunctionUpsert],
    functions_embeddings: list[list[float]],
    api_key_id: UUID | None = None,
) -> list[Function]:
    """
    Create functions.
    Note: each function might be of different app.
    """
    logger.debug(f"Creating functions, functions_upsert={functions_upsert}")

    functions = []
    for i, function_upsert in enumerate(functions_upsert):
        app_name = utils.parse_app_name_from_function_name(function_upsert.name)
        app = crud.apps.get_app_by_name_and_api_key_id(db_session, app_name, api_key_id)
        if not app:
            logger.error(f"App={app_name} does not exist for function={function_upsert.name}")
            raise ValueError(f"App={app_name} does not exist for function={function_upsert.name}")

        function_data = function_upsert.model_dump(mode="json", exclude_none=True)
        function = Function(
            app_id=app.id,
            **function_data,
            embedding=functions_embeddings[i],
            api_key_id=api_key_id,
        )
        db_session.add(function)
        functions.append(function)

    db_session.flush()

    return functions


def update_functions(
    db_session: Session,
    functions_upsert: list[FunctionUpsert],
    functions_embeddings: list[list[float] | None],
    api_key_id: UUID,
) -> list[Function]:
    """
    Update functions.
    Note: each function might be of different app.
    With the option to update the function embedding. (needed if FunctionEmbeddingFields are updated)
    """
    logger.debug(f"Updating functions, functions_upsert={functions_upsert}")
    functions = []
    for i, function_upsert in enumerate(functions_upsert):
        function = crud.functions.get_function_by_name_and_api_key_id(db_session, function_upsert.name, api_key_id)
        if not function:
            logger.error(f"Function={function_upsert.name} does not exist")
            raise ValueError(f"Function={function_upsert.name} does not exist")

        function_data = function_upsert.model_dump(mode="json", exclude_unset=True)
        for field, value in function_data.items():
            setattr(function, field, value)
        if functions_embeddings[i] is not None:
            function.embedding = functions_embeddings[i]  # type: ignore
        functions.append(function)

    db_session.flush()

    return functions


def search_functions(
    db_session: Session,
    public_only: bool,
    active_only: bool,
    app_names: list[str] | None,
    function_names: list[str] | None,
    intent_embedding: list[float] | None,
    limit: int,
    offset: int,
    exclude_api_key_owned: bool = True,
) -> list[Function]:
    """Get a list of functions with optional filtering by app names and sorting by vector similarity to intent."""
    statement = select(Function).join(App, Function.app_id == App.id)

    # filter out all functions of inactive apps and all inactive functions
    # (where app is active buy specific functions can be inactive)
    if active_only:
        statement = statement.filter(App.active).filter(Function.active)
    # if the corresponding project (api key belongs to) can only access public apps and functions,
    # filter out all functions of private apps and all private functions (where app is public but specific function is private)
    if public_only:
        statement = statement.filter(App.visibility == Visibility.PUBLIC).filter(
            Function.visibility == Visibility.PUBLIC
        )

    # filter out functions that are not in the specified function names
    if function_names is not None:
        statement = statement.filter(Function.name.in_(function_names))

    # filter out functions that are not in the specified apps
    if app_names is not None:
        statement = statement.filter(App.name.in_(app_names))

    # Exclude functions created by API keys (custom tools) unless explicitly requested
    if exclude_api_key_owned:
        try:
            statement = statement.filter(Function.api_key_id.is_(None))
        except Exception as e:
            if "column functions.api_key_id does not exist" in str(e):
                logger.warning("api_key_id column does not exist yet in functions table. Skipping filter.")
            else:
                raise

    if intent_embedding is not None:
        similarity_score = Function.embedding.cosine_distance(intent_embedding)
        statement = statement.order_by(similarity_score)

    statement = statement.offset(offset).limit(limit)
    logger.debug(f"Executing statement, statement={statement}")

    return list(db_session.execute(statement).scalars().all())


def get_functions(
    db_session: Session,
    public_only: bool,
    active_only: bool,
    app_names: list[str] | None,
    limit: int,
    offset: int,
) -> list[Function]:
    """Get a list of functions and their details. Sorted by function name."""
    statement = select(Function).join(App, Function.app_id == App.id)

    if app_names is not None:
        statement = statement.filter(App.name.in_(app_names))

    # exclude private Apps's functions and private functions if public_only is True
    if public_only:
        statement = statement.filter(App.visibility == Visibility.PUBLIC).filter(
            Function.visibility == Visibility.PUBLIC
        )
    # exclude inactive functions (including all functions if apps are inactive)
    if active_only:
        statement = statement.filter(App.active).filter(Function.active)

    statement = statement.order_by(Function.name).offset(offset).limit(limit)

    return list(db_session.execute(statement).scalars().all())


def get_functions_by_app_id(db_session: Session, app_id: UUID) -> list[Function]:
    statement = select(Function).filter(Function.app_id == app_id)

    return list(db_session.execute(statement).scalars().all())


def get_function(
    db_session: Session, function_name: str, public_only: bool, active_only: bool, api_key_id: UUID | None = None
) -> Function | None:
    statement = select(Function).filter(Function.name == function_name)

    # filter out all functions of inactive apps and all inactive functions
    # (where app is active buy specific functions can be inactive)
    if active_only:
        statement = (
            statement.join(App, Function.app_id == App.id)
            .filter(App.active)
            .filter(Function.active)
        )
    # if the corresponding project (api key belongs to) can only access public apps and functions,
    # filter out all functions of private apps and all private functions (where app is public but specific function is private)
    if public_only:
        statement = statement.filter(App.visibility == Visibility.PUBLIC).filter(
            Function.visibility == Visibility.PUBLIC
        )

    # Fetch all matches first, then prefer user's api_key_id, else fall back to LYZR_API_KEY_ID_DB
    functions = list(db_session.execute(statement).scalars().all())

    if not functions:
        return None

    if api_key_id is not None:
        for function in functions:
            if getattr(function, "api_key_id", None) == api_key_id:
                return function

    # Read at call time: the value is seeded during server startup (see
    # aci.common.platform_api_key.seed_env_from_db), so a module-level constant would
    # capture None on a fresh deployment.
    lyzr_api_key_id = get_lyzr_api_key_id()
    for function in functions:
        if getattr(function, "api_key_id", None) == lyzr_api_key_id:
            return function

    return functions[0]


def get_functions_by_names(
    db_session: Session, function_names: list[str], public_only: bool, active_only: bool
) -> list[Function]:
    """Get functions by a list of function names with the same filtering logic as get_function."""
    if not function_names:
        return []

    statement = select(Function).filter(Function.name.in_(function_names))

    # filter out all functions of inactive apps and all inactive functions
    # (where app is active buy specific functions can be inactive)
    if active_only:
        statement = (
            statement.join(App, Function.app_id == App.id)
            .filter(App.active)
            .filter(Function.active)
        )
    # if the corresponding project (api key belongs to) can only access public apps and functions,
    # filter out all functions of private apps and all private functions (where app is public but specific function is private)
    if public_only:
        statement = statement.filter(App.visibility == Visibility.PUBLIC).filter(
            Function.visibility == Visibility.PUBLIC
        )

    return list(db_session.execute(statement).scalars().all())

def get_function_by_name_and_api_key_id(
    db_session: Session,
    function_name: str,
    api_key_id: UUID,
) -> Function | None:
    """Get a function created by a specific API key."""
    try:
        statement = select(Function).filter(Function.name == function_name, Function.api_key_id == api_key_id)
        return db_session.execute(statement).scalars().first()
    except Exception as e:
        if "column functions.api_key_id does not exist" in str(e):
            logger.warning("api_key_id column does not exist yet in functions table. Returning None.")
            return None
        raise


def set_function_active_status(db_session: Session, function_name: str, active: bool) -> None:
    statement = update(Function).filter_by(name=function_name).values(active=active)
    db_session.execute(statement)


def set_function_visibility(
    db_session: Session, function_name: str, visibility: Visibility
) -> None:
    statement = update(Function).filter_by(name=function_name).values(visibility=visibility)
    db_session.execute(statement)


def get_functions_by_api_key_id(
    db_session: Session,
    api_key_id: UUID,
) -> list[Function]:
    """Get all functions created by a specific API key."""
    try:
        statement = select(Function).filter(Function.api_key_id == api_key_id)
        return list(db_session.execute(statement).scalars().all())
    except Exception as e:
        if "column functions.api_key_id does not exist" in str(e):
            logger.warning("api_key_id column does not exist yet in functions table. Returning empty list.")
            return []
        raise


def delete_function_by_id(
    db_session: Session,
    function_id: UUID,
    api_key_id: UUID,
) -> bool:
    """Delete a function if it was created by the given API key."""
    try:
        function = db_session.execute(
            select(Function).filter(Function.id == function_id, Function.api_key_id == api_key_id)
        ).scalar_one_or_none()

        if function:
            db_session.delete(function)
            db_session.flush()
            return True
        return False
    except Exception as e:
        if "column functions.api_key_id does not exist" in str(e):
            logger.warning("api_key_id column does not exist yet in functions table. Cannot delete function.")
            return False
        raise


def delete_functions_by_app_name(
    db_session: Session,
    app_name: str,
    api_key_id: UUID,
) -> int:
    """Delete all functions for a given app name. If api_key_id is provided, only delete functions created by that API key.
    Note: This function is typically used for custom apps only, not system apps."""
    try:
        # Get the app first to get its ID
        app = crud.apps.get_app_by_name_and_api_key_id(db_session, app_name, api_key_id)
        if not app:
            logger.warning(f"App '{app_name}' not found")
            return 0

        # Build the query to get functions for this app
        statement = select(Function).filter(Function.app_id == app.id)

        # If api_key_id is provided, only delete functions created by that API key
        if api_key_id is not None:
            statement = statement.filter(Function.api_key_id == api_key_id)

        # Get all functions to delete
        functions_to_delete = list(db_session.execute(statement).scalars().all())

        # Delete each function
        for function in functions_to_delete:
            db_session.delete(function)

        db_session.flush()

        logger.info(f"Deleted {len(functions_to_delete)} functions for app '{app_name}'")
        return len(functions_to_delete)

    except Exception as e:
        if "column functions.api_key_id does not exist" in str(e):
            logger.warning("api_key_id column does not exist yet in functions table. Cannot filter by API key.")
            # Fallback: delete all functions for the app without API key filtering
            app = crud.apps.get_app_by_name_and_api_key_id(db_session, app_name, api_key_id)
            if not app:
                return 0

            statement = select(Function).filter(Function.app_id == app.id)
            functions_to_delete = list(db_session.execute(statement).scalars().all())

            for function in functions_to_delete:
                db_session.delete(function)

            db_session.flush()
            return len(functions_to_delete)
        raise
