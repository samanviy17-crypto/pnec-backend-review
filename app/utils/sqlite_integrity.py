"""SQLite must enforce the same relational constraints as production MySQL."""
from sqlalchemy import event


def enforce_foreign_keys(engine):
    if engine.dialect.name != 'sqlite':
        return

    @event.listens_for(engine, 'connect')
    def enable(connection, record):
        # sqlite3 ignores this pragma inside a transaction (Python 3.12+ too).
        previous = getattr(connection, 'autocommit', None)
        if previous is not None:
            connection.autocommit = True
        try:
            cursor = connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.execute('PRAGMA foreign_keys')
            if cursor.fetchone()[0] != 1:
                raise RuntimeError('SQLite foreign-key enforcement is required.')
            cursor.close()
        finally:
            if previous is not None:
                connection.autocommit = previous
