"""
CRUD operations for apps. (not including app_configurations)
"""

import os
from uuid import UUID

from sqlalchemy import delete as sql_delete, select, update, or_
from sqlalchemy.orm import Session

from aci.common.db.sql_models import App, AppConfiguration, LinkedAccount
from aci.common.enums import SecurityScheme, Visibility
from aci.common.logging_setup import get_logger
from aci.common.schemas.app import AppUpsert

logger = get_logger(__name__)


def create_app(
    db_session: Session,
    app_upsert: AppUpsert,
    app_embedding: list[float],
    api_key_id: UUID | None = None,
) -> App:
    logger.debug(f"Creating app: {app_upsert}")

    app_data = app_upsert.model_dump(mode="json", exclude_none=True)
    app = App(
        **app_data,
        embedding=app_embedding,
        api_key_id=api_key_id,
    )

    db_session.add(app)
    db_session.flush()
    db_session.refresh(app)
    return app


def update_app(
    db_session: Session,
    app: App,
    app_upsert: AppUpsert,
    app_embedding: list[float] | None = None,
) -> App:
    """
    Update an existing app.
    With the option to update the app embedding. (needed if AppEmbeddingFields are updated)
    """
    new_app_data = app_upsert.model_dump(mode="json", exclude_unset=True)

    for field, value in new_app_data.items():
        setattr(app, field, value)

    if app_embedding is not None:
        app.embedding = app_embedding

    db_session.flush()
    db_session.refresh(app)
    return app


def update_app_default_security_credentials(
    db_session: Session,
    app: App,
    security_scheme: SecurityScheme,
    security_credentials: dict,
) -> None:
    # Note: this update works because of the MutableDict.as_mutable(JSON) in the sql_models.py
    # TODO: check if this is the best practice and double confirm that nested dict update does NOT work
    app.default_security_credentials_by_scheme[security_scheme] = security_credentials


def get_app(db_session: Session, app_name: str, public_only: bool, active_only: bool, api_key_id: UUID | None = None) -> App | None:
    statement = select(App).filter_by(name=app_name)
    LYZR_API_KEY_ID_DB = UUID(os.getenv("LYZR_API_KEY_ID_DB"))

    if active_only:
        statement = statement.filter(App.active)
    if public_only:
        statement = statement.filter(App.visibility == Visibility.PUBLIC)
    if api_key_id is not None:
        statement = statement.filter(or_(App.api_key_id == api_key_id, App.api_key_id == LYZR_API_KEY_ID_DB))
        # Prioritize exact api_key_id match first, then fallback to LYZR_API_KEY_ID_DB
        statement = statement.order_by((App.api_key_id == api_key_id).desc())
    app: App | None = db_session.execute(statement).scalars().first()
    return app


def get_app_by_id(db_session: Session, app_id: UUID) -> App | None:
    """Get an app by its ID"""
    statement = select(App).filter_by(id=app_id)
    app: App | None = db_session.execute(statement).scalars().first()
    return app


def get_apps(
    db_session: Session,
    public_only: bool,
    active_only: bool,
    app_names: list[str] | None,
    limit: int | None,
    offset: int | None,
    api_key_id: UUID | None = None,
) -> list[App]:
    statement = select(App)
    if public_only:
        statement = statement.filter(App.visibility == Visibility.PUBLIC)
    if active_only:
        statement = statement.filter(App.active)
    if app_names is not None:
        statement = statement.filter(App.name.in_(app_names))

    LYZR_API_KEY_ID_DB = UUID(os.getenv("LYZR_API_KEY_ID_DB"))

    if api_key_id is not None:
        try:
            statement = statement.filter(or_(App.api_key_id == api_key_id, App.api_key_id == LYZR_API_KEY_ID_DB))
        except Exception as e:
            if "column apps.api_key_id does not exist" in str(e):
                logger.warning("api_key_id column does not exist yet in apps table. Skipping filter.")
            else:
                raise
    if offset is not None:
        statement = statement.offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    return list(db_session.execute(statement).scalars().all())


def search_apps(
    db_session: Session,
    public_only: bool,
    active_only: bool,
    app_names: list[str] | None,
    categories: list[str] | None,
    intent_embedding: list[float] | None,
    limit: int,
    offset: int,
) -> list[tuple[App, float | None]]:
    """Get a list of apps with optional filtering by categories and sorting by vector similarity to intent. and pagination."""
    statement = select(App)

    # filter out private apps
    if public_only:
        statement = statement.filter(App.visibility == Visibility.PUBLIC)

    # filter out inactive apps
    if active_only:
        statement = statement.filter(App.active)

    # filter out apps by app_names
    if app_names is not None:
        statement = statement.filter(App.name.in_(app_names))

    # filter out apps by categories
    # TODO: Is there any way to get typing for cosine_distance, label, overlap?
    if categories is not None:
        statement = statement.filter(App.categories.overlap(categories))

    # sort by similarity to intent
    if intent_embedding is not None:
        similarity_score = App.embedding.cosine_distance(intent_embedding)
        statement = statement.add_columns(similarity_score.label("similarity_score"))
        statement = statement.order_by("similarity_score")

    statement = statement.offset(offset).limit(limit)

    logger.debug(f"Executing statement, statement={statement}")

    results = db_session.execute(statement).all()

    if intent_embedding is not None:
        return [(app, score) for app, score in results]
    else:
        return [(app, None) for (app,) in results]


def get_apps_by_api_key_id(
    db_session: Session,
    api_key_id: UUID,
) -> list[App]:
    """Get all apps created by a specific API key."""
    try:
        statement = select(App).filter(App.api_key_id == api_key_id)
        return list(db_session.execute(statement).scalars().all())
    except Exception as e:
        if "column apps.api_key_id does not exist" in str(e):
            logger.warning("api_key_id column does not exist yet in apps table. Returning empty list.")
            return []
        raise

def get_app_by_name_and_api_key_id(
    db_session: Session,
    app_name: str,
    api_key_id: UUID,
) -> App | None:
    """Get an app created by a specific API key."""
    try:
        statement = select(App).filter(App.name == app_name, App.api_key_id == api_key_id)
        return db_session.execute(statement).scalar_one_or_none()
    except Exception as e:
        if "column apps.api_key_id does not exist" in str(e):
            logger.warning("api_key_id column does not exist yet in apps table. Returning None.")
            return None
        raise


def delete_app_by_id(
    db_session: Session,
    app_id: UUID,
    api_key_id: UUID,
) -> bool:
    """Delete an app if it was created by the given API key.

    Explicitly removes AppConfiguration and LinkedAccount rows that reference
    this app before deleting the app itself, because App has no ORM cascade to
    those tables and Postgres FK constraints would otherwise reject the DELETE.
    """
    try:
        app = db_session.execute(
            select(App).filter(App.id == app_id, App.api_key_id == api_key_id)
        ).scalar_one_or_none()

        if not app:
            return False

        # Delete dependents with synchronize_session=False to bypass identity-map
        # evaluation, then flush immediately so the rows are gone in the DB before
        # we attempt to DELETE the app row (which has no ORM cascade to these tables).
        db_session.execute(
            sql_delete(LinkedAccount)
            .where(LinkedAccount.app_id == app_id)
            .execution_options(synchronize_session=False)
        )
        db_session.execute(
            sql_delete(AppConfiguration)
            .where(AppConfiguration.app_id == app_id)
            .execution_options(synchronize_session=False)
        )
        db_session.flush()

        db_session.delete(app)
        db_session.flush()
        return True
    except Exception as e:
        if "column apps.api_key_id does not exist" in str(e):
            logger.warning("api_key_id column does not exist yet in apps table. Cannot delete app.")
            return False
        raise


def set_app_active_status(db_session: Session, app_name: str, active: bool) -> None:
    statement = update(App).filter_by(name=app_name).values(active=active)
    db_session.execute(statement)


def set_app_visibility(db_session: Session, app_name: str, visibility: Visibility) -> None:
    statement = update(App).filter_by(name=app_name).values(visibility=visibility)
    db_session.execute(statement)
