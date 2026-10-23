"""Retain charged provider usage after demo session deletion."""

from alembic import op

revision = "002"
down_revision = "001"


def upgrade():
    op.execute("ALTER TABLE usage ALTER COLUMN space DROP NOT NULL")
    op.execute("ALTER TABLE usage DROP CONSTRAINT IF EXISTS usage_space_fkey")
    op.execute(
        "ALTER TABLE usage ADD CONSTRAINT usage_space_fkey FOREIGN KEY (space) REFERENCES spaces(id) ON DELETE SET NULL"
    )


def downgrade():
    pass
