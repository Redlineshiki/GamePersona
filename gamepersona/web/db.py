from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def connect(self):
        with psycopg.connect(self.dsn,row_factory=dict_row,connect_timeout=5) as con:
            yield con

    def migrate(self):
        with self.connect() as con:
            con.execute('SELECT pg_advisory_xact_lock(53170001)')
            con.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version integer PRIMARY KEY)')
            if not con.execute('SELECT 1 FROM schema_migrations WHERE version=1').fetchone():
                con.execute((Path(__file__).parent/'migrations'/'001_initial.sql').read_text(encoding='utf-8'))
                con.execute('INSERT INTO schema_migrations VALUES(1)')
