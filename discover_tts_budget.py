"""Budget local conservateur : chaque appel est engagé avant son envoi, sans réessai automatique."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MICRODOLLARS_PER_CHARACTER = 30  # Aura-2 : 0,03 USD / 1 000 caractères.


class BudgetDepasse(RuntimeError):
    pass


class AppelIncertain(RuntimeError):
    pass


class Budget:
    def __init__(self, root, month=None):
        self.path = Path(root) / 'usage.sqlite'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.month = month or (lambda: datetime.now(timezone.utc).strftime('%Y-%m'))
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS requests
                (key TEXT PRIMARY KEY, month TEXT NOT NULL, characters INTEGER NOT NULL,
                 cost_micro INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self, limit_usd):
        with self.connection() as db:
            row = db.execute('SELECT COALESCE(SUM(cost_micro),0), COUNT(*), '
                             "COALESCE(SUM(status<>'complete'),0) FROM requests WHERE month=?", (self.month(),)).fetchone()
        return {'month': self.month(), 'engagedUsd': row[0] / 1_000_000,
                'remainingUsd': max(0, limit_usd - row[0] / 1_000_000),
                'requests': row[1], 'uncertainRequests': row[2]}

    def attempted(self, key):
        with self.connection() as db:
            return db.execute('SELECT 1 FROM requests WHERE key=?', (key,)).fetchone() is not None

    def reserve(self, key, characters, limit_usd):
        cost = characters * MICRODOLLARS_PER_CHARACTER
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM requests WHERE key=?', (key,)).fetchone():
                raise AppelIncertain('Ce fragment a déjà été envoyé ; aucun nouvel appel payant automatique.')
            used = db.execute('SELECT COALESCE(SUM(cost_micro),0) FROM requests WHERE month=?', (self.month(),)).fetchone()[0]
            if used + cost > round(limit_usd * 1_000_000):
                raise BudgetDepasse('Plafond mensuel Deepgram atteint.')
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?)',
                       (key, self.month(), characters, cost, 'reserved', datetime.now(timezone.utc).isoformat()))

    def finish(self, key, success):
        with self.connection() as db:
            db.execute('UPDATE requests SET status=? WHERE key=?', ('complete' if success else 'uncertain', key))
