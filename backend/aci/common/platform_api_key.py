"""Find-or-create the platform API key whose id is ``LYZR_API_KEY_ID_DB``.

``LYZR_API_KEY_ID_DB`` holds the ``api_keys.id`` of the platform/system API key.
Platform-seeded apps and functions are stored with ``apps.api_key_id`` set to it,
and ``aci.common.utils.get_lyzr_api_key_id`` is the fallback owner used when
resolving apps/functions for a caller. When it is unset, those filters degrade to
``api_key_id IS NULL`` and no platform tool is visible.

This module is the single source of truth for how that row is selected, so the
server's startup seeding (``seed_env_from_db``), the ``ensure-platform-api-key``
CLI command and ``scripts/seed_lyzr_api_key_id.py`` (the HTTP variant used against
an already-running deployment) all converge on the same API key:

    the oldest active API key of the oldest project of ``org_id``,
    preferring a project named ``project_name``; ties broken by id.

Selection is therefore stable across restarts: the first boot creates the project,
every later boot finds it.
"""

from __future__ import annotations

import hashlib
import os
import time
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from aci.common import utils
from aci.common.db import crud
from aci.common.db.sql_models import Agent, APIKey, Project
from aci.common.enums import APIKeyStatus
from aci.common.logging_setup import get_logger

ENV_VAR = "LYZR_API_KEY_ID_DB"
AUTO_SEED_ENV_VAR = "LYZR_API_KEY_ID_AUTO_SEED"
ORG_ID_ENV_VAR = "LYZR_PLATFORM_ORG_ID"
PROJECT_NAME_ENV_VAR = "LYZR_PLATFORM_PROJECT_NAME"

# Synthetic org that owns the platform project. Deliberately not a real customer
# org: the platform key must not disappear when a customer org is deleted, and the
# platform project must not eat a customer's SERVER_MAX_PROJECTS_PER_ORG budget.
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_PROJECT_NAME = "Default Org"
DEFAULT_AGENT_NAME = "Default Agent"

logger = get_logger(__name__)


def auto_seed_enabled() -> bool:
    return os.getenv(AUTO_SEED_ENV_VAR, "true").strip().lower() == "true"


def platform_org_id() -> str:
    return os.getenv(ORG_ID_ENV_VAR) or DEFAULT_ORG_ID


def platform_project_name() -> str:
    return os.getenv(PROJECT_NAME_ENV_VAR) or DEFAULT_PROJECT_NAME


def _select_platform_api_key(org_id: str, project_name: str) -> Select[tuple[UUID]]:
    """Single-statement version of the documented selection rule."""
    return (
        select(APIKey.id)
        .join(Agent, APIKey.agent_id == Agent.id)
        .join(Project, Agent.project_id == Project.id)
        .filter(Project.org_id == org_id)
        .filter(APIKey.status == APIKeyStatus.ACTIVE)
        .order_by(
            (Project.name == project_name).desc(),
            Project.created_at.asc(),
            Project.id.asc(),
            APIKey.created_at.asc(),
            APIKey.id.asc(),
        )
        .limit(1)
    )


def _acquire_org_lock(db_session: Session, org_id: str) -> None:
    """Serialize find-or-create across concurrent replicas/workers.

    Transaction-scoped Postgres advisory lock, so it is released on commit or
    rollback. Without it, two replicas booting against a fresh DB would each
    create a project and could disagree on which one is "oldest".
    """
    if db_session.bind is None or db_session.bind.dialect.name != "postgresql":
        return
    digest = hashlib.blake2b(f"lyzr_platform_api_key:{org_id}".encode(), digest_size=8).digest()
    lock_key = int.from_bytes(digest, "big", signed=True)
    db_session.execute(select(func.pg_advisory_xact_lock(lock_key)))


def api_key_exists(db_session: Session, api_key_id: UUID) -> bool:
    return (
        db_session.execute(select(APIKey.id).filter(APIKey.id == api_key_id)).scalar_one_or_none()
        is not None
    )


def find_platform_api_key_id(
    db_session: Session, org_id: str, project_name: str = DEFAULT_PROJECT_NAME
) -> UUID | None:
    """Return the platform ``api_keys.id`` for ``org_id``, without creating anything."""
    return db_session.execute(_select_platform_api_key(org_id, project_name)).scalar_one_or_none()


def ensure_platform_api_key_id(
    db_session: Session,
    org_id: str,
    project_name: str = DEFAULT_PROJECT_NAME,
    *,
    allow_create: bool = True,
) -> tuple[UUID | None, bool]:
    """Find the platform API key, creating the project + default agent if missing.

    Returns ``(api_key_id, created)``. ``created`` is True only on the first run
    against a fresh database. Commits when it creates; otherwise leaves the
    session untouched apart from the advisory lock.
    """
    _acquire_org_lock(db_session, org_id)

    api_key_id = find_platform_api_key_id(db_session, org_id, project_name)
    if api_key_id is not None:
        return api_key_id, False
    if not allow_create:
        return None, False

    # Mirrors POST /v1/projects: a project plus its "Default Agent", whose
    # creation also mints the agent's API key.
    project = crud.projects.create_project(db_session, org_id, project_name)
    agent = crud.projects.create_agent(
        db_session,
        project.id,
        name=DEFAULT_AGENT_NAME,
        description=DEFAULT_AGENT_NAME,
        allowed_apps=[],
        custom_instructions={},
    )
    api_key = crud.projects.get_api_key_by_agent_id(db_session, agent.id)
    if api_key is None:
        db_session.rollback()
        raise RuntimeError(f"no API key was created for agent {agent.id}")

    api_key_id = api_key.id
    db_session.commit()
    logger.info(
        f"Created platform project, project_id={project.id}, agent_id={agent.id}, "
        f"api_key_id={api_key_id}, org_id={org_id}"
    )
    return api_key_id, True


def seed_env_from_db(
    db_url: str,
    *,
    org_id: str | None = None,
    project_name: str | None = None,
    retries: int = 5,
    retry_delay: float = 2.0,
) -> UUID | None:
    """Populate ``os.environ[LYZR_API_KEY_ID_DB]`` at server startup.

    Never raises: a deployment must boot even when the platform key cannot be
    resolved (e.g. migrations have not created the tables yet). It logs loudly
    instead, and ``scripts/seed_lyzr_api_key_id.py`` / the
    ``ensure-platform-api-key`` CLI command can be used to fix it up.

    Must run before the value is first read. Callers of
    ``aci.common.utils.get_lyzr_api_key_id`` read ``os.environ`` on every call, so
    setting it in the FastAPI startup event is early enough.
    """
    configured = os.getenv(ENV_VAR)
    if configured:
        # An explicitly configured value always wins; only sanity-check it.
        try:
            api_key_id = UUID(configured)
        except ValueError:
            logger.error(f"{ENV_VAR}={configured!r} is not a UUID; platform tools will be hidden")
            return None
        try:
            with utils.create_db_session(db_url) as db_session:
                if not api_key_exists(db_session, api_key_id):
                    logger.error(
                        f"{ENV_VAR}={api_key_id} does not exist in api_keys; platform tools "
                        "seeded under it will be hidden"
                    )
        except SQLAlchemyError as error:
            logger.warning(f"Could not verify {ENV_VAR}: {error}")
        else:
            logger.info(f"{ENV_VAR} already configured ({api_key_id}); skipping platform seeding")
        return api_key_id

    if not auto_seed_enabled():
        logger.warning(
            f"{ENV_VAR} is unset and {AUTO_SEED_ENV_VAR} is false; platform-seeded apps and "
            "functions will not be visible"
        )
        return None

    org_id = org_id or platform_org_id()
    project_name = project_name or platform_project_name()

    for attempt in range(1, max(retries, 1) + 1):
        try:
            with utils.create_db_session(db_url) as db_session:
                seeded_id, created = ensure_platform_api_key_id(db_session, org_id, project_name)
        except (SQLAlchemyError, RuntimeError) as error:
            if attempt >= max(retries, 1):
                logger.error(
                    f"Could not resolve {ENV_VAR} after {attempt} attempt(s): {error}. "
                    "Platform-seeded apps and functions will not be visible until this is set "
                    "(see scripts/seed_lyzr_api_key_id.py)."
                )
                return None
            logger.warning(f"Platform key seeding attempt {attempt}/{retries} failed: {error}")
            time.sleep(retry_delay)
            continue

        if seeded_id is None:
            logger.error(f"Could not resolve {ENV_VAR} for org {org_id}")
            return None

        os.environ[ENV_VAR] = str(seeded_id)
        logger.info(
            f"{ENV_VAR}={seeded_id} ({'created' if created else 'existing'} platform project, "
            f"org_id={org_id})"
        )
        return seeded_id

    return None
