"""Removing a test space while the background worker may still be finishing one of its jobs."""

import time

from sqlalchemy.exc import OperationalError

from app.db import Space, db


def drop_space(space_id, attempts=5):
    """The cascade delete and the worker can lock the same rows in opposite order; PostgreSQL then aborts one of
    them as a deadlock. The worker retries its job on its own, the test retries the delete."""
    for attempt in range(attempts):
        try:
            with db() as s:
                sp = s.get(Space, space_id)
                if sp:
                    s.delete(sp)
            return
        except OperationalError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.3 * (attempt + 1))
