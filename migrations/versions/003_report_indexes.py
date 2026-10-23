from alembic import op
from sqlalchemy import text

revision = "003_report_indexes"
down_revision = "002"


def upgrade():
    op.create_index("entries_space_date", "entries", ["space", "date"])
    op.create_index("entries_space_contract", "entries", ["space", "contract"])
    op.create_index("jobs_pending_due", "jobs", ["due"], postgresql_where=text("state = 'pending'"))


def downgrade():
    op.drop_index("jobs_pending_due")
    op.drop_index("entries_space_contract")
    op.drop_index("entries_space_date")
