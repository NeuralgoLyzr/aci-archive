import logging
from uuid import UUID

from propelauth_fastapi import FastAPIAuth, User, init_auth
from sqlalchemy.orm import Session

from aci.common.db import crud
from aci.common.enums import OrganizationRole
from aci.common.exceptions import ProjectNotFound
from aci.server import config

logger = logging.getLogger(__name__)


class _UnconfiguredAuth:
    """Stand-in for FastAPIAuth when PropelAuth env vars aren't set.

    Lets modules that do `auth = acl.get_propelauth()` and
    `Depends(auth.require_user)` at import time keep working — the app can
    still start and serve unauthenticated routes (e.g. health checks) — but
    any authenticated route fails clearly (503) instead of at import time.
    """

    def __getattr__(self, name: str) -> object:
        def _unconfigured(*args: object, **kwargs: object) -> None:
            raise RuntimeError(
                "PropelAuth is not configured: set SERVER_PROPELAUTH_AUTH_URL and "
                "SERVER_PROPELAUTH_API_KEY to enable authenticated routes."
            )

        return _unconfigured


_auth: FastAPIAuth
if config.PROPELAUTH_AUTH_URL and config.PROPELAUTH_API_KEY:
    _auth = init_auth(config.PROPELAUTH_AUTH_URL, config.PROPELAUTH_API_KEY)
else:
    logger.warning(
        "SERVER_PROPELAUTH_AUTH_URL / SERVER_PROPELAUTH_API_KEY are not set — "
        "authenticated routes will fail until they are configured."
    )
    _auth = _UnconfiguredAuth()  # type: ignore[assignment]


def get_propelauth() -> FastAPIAuth:
    return _auth


def validate_user_access_to_org(user: User, org_id: str) -> None:
    # TODO: Change to require_org_member_with_minimum_role and require_org_member once projects have been refactored to use
    # TODO: org_id in the header. Currently they we have project_id so this function and validate_user_access_to_project are still useful.
    # Use PropelAuth's built-in method to validate organization role
    get_propelauth().require_org_member(user, org_id)


def validate_user_access_to_project(db_session: Session, user: User, project_id: UUID) -> None:
    # TODO: refactor to use PropelAuth built-in methods
    # TODO: we can introduce project level ACLs later
    project = crud.projects.get_project(db_session, project_id)
    if not project:
        raise ProjectNotFound(f"project={project_id} not found")

    validate_user_access_to_org(user, project.org_id)


def require_org_member(user: User, org_id: str) -> None:
    get_propelauth().require_org_member(user, org_id)


def require_org_member_with_minimum_role(
    user: User, org_id: str, minimum_role: OrganizationRole
) -> None:
    get_propelauth().require_org_member_with_minimum_role(user, org_id, minimum_role)
