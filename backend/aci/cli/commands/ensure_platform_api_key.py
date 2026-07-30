"""Print the ``LYZR_API_KEY_ID_DB`` value for this deployment's database.

Same find-or-create logic the server runs at startup
(``aci.common.platform_api_key``), exposed for infra: it talks to the DB directly, so
it works before the server is up (init container, migration job, docker compose exec).
Use ``scripts/seed_lyzr_api_key_id.py`` instead when only the deployment's HTTP
endpoint is reachable.

Only the resolved UUID goes to stdout, so it can be captured directly:

    export LYZR_API_KEY_ID_DB=$(python -m aci.cli ensure-platform-api-key)
"""

import click
from rich.console import Console

from aci.cli import config
from aci.common import platform_api_key, utils

# stderr, so stdout stays a bare UUID
console = Console(stderr=True)


@click.command()
@click.option(
    "--org-id",
    "org_id",
    default=None,
    help=f"org that owns the platform project [env: {platform_api_key.ORG_ID_ENV_VAR}] "
    f"(default: {platform_api_key.DEFAULT_ORG_ID})",
)
@click.option(
    "--name",
    "project_name",
    default=None,
    help=f"platform project name [env: {platform_api_key.PROJECT_NAME_ENV_VAR}] "
    f"(default: {platform_api_key.DEFAULT_PROJECT_NAME!r})",
)
@click.option(
    "--no-create",
    is_flag=True,
    help="fail instead of creating the project when it does not exist yet (read-only check)",
)
def ensure_platform_api_key(org_id: str | None, project_name: str | None, no_create: bool) -> None:
    """Find (or create on first run) the platform API key and print its api_keys.id."""
    org_id = org_id or platform_api_key.platform_org_id()
    project_name = project_name or platform_api_key.platform_project_name()

    with utils.create_db_session(config.get_db_full_url_sync()) as db_session:
        api_key_id, created = platform_api_key.ensure_platform_api_key_id(
            db_session, org_id, project_name, allow_create=not no_create
        )

    if api_key_id is None:
        raise click.ClickException(
            f"no platform API key for org {org_id} (project {project_name!r})"
            + (" and --no-create was passed" if no_create else "")
        )

    console.print(
        f"[bold green]{'Created' if created else 'Found'}[/bold green] platform API key for "
        f"org {org_id} (project {project_name!r})"
    )
    click.echo(str(api_key_id))
