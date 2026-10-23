from app.db import db
from sqlalchemy import text
with db() as s:
    row=s.execute(text("SELECT pid FROM pg_stat_activity WHERE pid=355157 AND datname=current_database() AND query LIKE 'WITH historic AS%' AND state='active'" )).first()
    if row:print('Cancelled test query:',s.scalar(text('SELECT pg_cancel_backend(:pid)'),{'pid':row.pid}))
