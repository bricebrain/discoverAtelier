"""Cache local des textes, vecteurs float32 et publications reprenables."""
import json
import sqlite3
from array import array
from pathlib import Path


class Store:
    def __init__(self, root):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / 'related.sqlite')
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS items(key TEXT PRIMARY KEY,data TEXT NOT NULL,fingerprint TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS vectors(fingerprint TEXT PRIMARY KEY,vector BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS published(key TEXT PRIMARY KEY,data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS judgments(key TEXT PRIMARY KEY,day TEXT NOT NULL,answer INTEGER);
        """)
        self.db.commit()
        (root / 'related.sqlite').chmod(0o600)

    def get(self, key, default=None):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))
        self.db.commit()

    def vector(self, fingerprint):
        row = self.db.execute('SELECT vector FROM vectors WHERE fingerprint=?', (fingerprint,)).fetchone()
        if row:
            v = array('f')
            v.frombytes(row[0])
            return list(v)

    def save_vector(self, fingerprint, vector):
        self.db.execute('INSERT OR REPLACE INTO vectors VALUES (?,?)', (fingerprint, array('f', vector).tobytes()))
        self.db.commit()

    def put(self, item, fingerprint):
        key = item['type'] + ':' + item['id']
        old = self.db.execute('SELECT data FROM items WHERE key=?', (key,)).fetchone()
        if not old or json.loads(old[0]) != item:
            # Corbeille/restauration entre deux passages : les triggers ont pu effacer les liens.
            for published_key, raw in self.db.execute('SELECT key,data FROM published').fetchall():
                data = json.loads(raw)
                references = [n['targetType']+':'+n['targetId'] for n in data.get('neighbors', [])]
                references += [m['type']+':'+m['id'] for m in data.get('members', [])]
                if published_key == 'source:'+key or key in references:
                    self.db.execute('DELETE FROM published WHERE key=?', (published_key,))
        if item.get('deleted'):
            self.db.execute('DELETE FROM items WHERE key=?', (key,))
        else:
            self.db.execute('INSERT OR REPLACE INTO items VALUES (?,?,?)', (key, json.dumps(item), fingerprint))
        self.db.commit()

    def all(self):
        return [(k, json.loads(d), f) for k, d, f in self.db.execute('SELECT * FROM items ORDER BY key')]

    def changed(self, key, data):
        row = self.db.execute('SELECT data FROM published WHERE key=?', (key,)).fetchone()
        return not row or row[0] != json.dumps(data, sort_keys=True)

    def ack(self, key, data):
        self.db.execute('INSERT OR REPLACE INTO published VALUES (?,?)', (key, json.dumps(data, sort_keys=True)))
        self.db.commit()

    def close(self):
        self.db.close()
