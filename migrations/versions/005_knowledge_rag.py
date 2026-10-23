from alembic import op

revision = "005_knowledge_rag"
down_revision = "004_linked_sessions"


def upgrade():
    op.execute(
        """CREATE TABLE kb_doc (id text PRIMARY KEY, title text NOT NULL, url text NOT NULL, version text NOT NULL, kind text NOT NULL, hash text NOT NULL)"""
    )
    op.execute(
        """CREATE TABLE kb_chunk (id text PRIMARY KEY, doc_id text NOT NULL REFERENCES kb_doc(id) ON DELETE CASCADE, n integer NOT NULL, text text NOT NULL, tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', text)) STORED, embedding vector(384) NOT NULL)"""
    )
    op.execute(
        "CREATE INDEX kb_chunk_vector ON kb_chunk USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX kb_chunk_fts ON kb_chunk USING gin (tsv)")
    op.execute(
        """CREATE TABLE source_sync (id varchar(32) PRIMARY KEY, space varchar(32) NOT NULL REFERENCES spaces(id) ON DELETE CASCADE, source text NOT NULL, status text NOT NULL, started timestamptz NOT NULL DEFAULT now(), finished timestamptz, execution_id text, data jsonb NOT NULL DEFAULT '{}')"""
    )
    op.execute("CREATE INDEX source_sync_space ON source_sync(space, started DESC)")


def downgrade():
    op.drop_table("source_sync")
    op.drop_table("kb_chunk")
    op.drop_table("kb_doc")
