"""reconcile schema with models: org_id varchar, apps/functions api_key_id + per-creator unique

The original migrations diverged from the ORM models in three ways, which broke a
fresh (e.g. Azure) deployment:

  * projects.org_id / subscriptions.org_id were created as UUID, but the models
    declare them String — org ids are opaque strings, not UUIDs.
  * apps.api_key_id / functions.api_key_id exist in the models (creator of a
    user-defined app/function; NULL = system/built-in) but no migration adds them.
  * apps / functions enforced a global UNIQUE(name); the intended semantics are
    per-creator uniqueness, UNIQUE(api_key_id, name), so multiple users can
    register a same-named app/function.

Written idempotently (IF EXISTS / IF NOT EXISTS) so it is safe both on a fresh DB
and on the Azure DB where these were already applied by hand.

Revision ID: c3f1a9d7b2e0
Revises: 48bf142a794c
Create Date: 2026-07-29 12:30:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f1a9d7b2e0"
down_revision: Union[str, None] = "48bf142a794c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # org_id: UUID -> VARCHAR (matches the String model). USING keeps it safe if
    # the column is already varchar (no-op) or still uuid.
    op.execute("ALTER TABLE projects ALTER COLUMN org_id TYPE VARCHAR USING org_id::text")
    op.execute("ALTER TABLE subscriptions ALTER COLUMN org_id TYPE VARCHAR USING org_id::text")

    # api_key_id creator column (nullable FK; NULL = system/built-in).
    op.execute("ALTER TABLE apps ADD COLUMN IF NOT EXISTS api_key_id UUID REFERENCES api_keys(id)")
    op.execute("ALTER TABLE functions ADD COLUMN IF NOT EXISTS api_key_id UUID REFERENCES api_keys(id)")

    # Per-creator uniqueness instead of global name uniqueness.
    op.execute("ALTER TABLE apps DROP CONSTRAINT IF EXISTS apps_name_key")
    op.execute("ALTER TABLE apps DROP CONSTRAINT IF EXISTS uc_apps_api_key_id_name")
    op.execute("ALTER TABLE apps ADD CONSTRAINT uc_apps_api_key_id_name UNIQUE (api_key_id, name)")
    op.execute("ALTER TABLE functions DROP CONSTRAINT IF EXISTS functions_name_key")
    op.execute("ALTER TABLE functions DROP CONSTRAINT IF EXISTS uc_functions_api_key_id_name")
    op.execute("ALTER TABLE functions ADD CONSTRAINT uc_functions_api_key_id_name UNIQUE (api_key_id, name)")


def downgrade() -> None:
    op.execute("ALTER TABLE apps DROP CONSTRAINT IF EXISTS uc_apps_api_key_id_name")
    op.execute("ALTER TABLE apps ADD CONSTRAINT apps_name_key UNIQUE (name)")
    op.execute("ALTER TABLE functions DROP CONSTRAINT IF EXISTS uc_functions_api_key_id_name")
    op.execute("ALTER TABLE functions ADD CONSTRAINT functions_name_key UNIQUE (name)")
    op.execute("ALTER TABLE apps DROP COLUMN IF EXISTS api_key_id")
    op.execute("ALTER TABLE functions DROP COLUMN IF EXISTS api_key_id")
    op.execute("ALTER TABLE projects ALTER COLUMN org_id TYPE UUID USING org_id::uuid")
    op.execute("ALTER TABLE subscriptions ALTER COLUMN org_id TYPE UUID USING org_id::uuid")
