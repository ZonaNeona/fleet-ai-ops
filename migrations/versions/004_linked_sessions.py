from alembic import op

revision = "004_linked_sessions"
down_revision = "003_report_indexes"


def upgrade():
    op.execute(
        "CREATE TABLE IF NOT EXISTS access_tokens (token varchar(64) PRIMARY KEY, space varchar(32) NOT NULL REFERENCES spaces(id) ON DELETE CASCADE, created timestamptz NOT NULL DEFAULT now())"
    )
    op.execute("CREATE INDEX IF NOT EXISTS access_tokens_space ON access_tokens(space)")


def downgrade():
    op.drop_table("access_tokens")
