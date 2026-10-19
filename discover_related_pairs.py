"""Calcul des cosinus par tranches reprenables, indépendant des publications."""
import hashlib
import itertools
import json

from discover_related_similarity import cosine, text


def prepare(store, rows, verifier, limit=10000):
    db = store.db
    db.execute('''CREATE TABLE IF NOT EXISTS pairs (
        a TEXT NOT NULL,b TEXT NOT NULL,fa TEXT NOT NULL,fb TEXT NOT NULL,score REAL NOT NULL,
        PRIMARY KEY(a,b))''')
    signature = hashlib.sha256(json.dumps([(k, f) for k, _, f, _ in rows]).encode()).hexdigest()
    if store.get('pairSignature') != signature:
        store.set('pairSignature', signature)
        store.set('pairCursor', 0)
        keys = {k for k, _, _, _ in rows}
        for a, b in db.execute('SELECT a,b FROM pairs').fetchall():
            if a not in keys or b not in keys:
                db.execute('DELETE FROM pairs WHERE a=? AND b=?', (a, b))
        db.commit()
    start = store.get('pairCursor', 0)
    total = len(rows) * (len(rows)-1) // 2
    end = min(total, start + limit)
    batch = itertools.islice(itertools.combinations(rows, 2), start, end)
    for count, ((ka, a, fa, va), (kb, b, fb, vb)) in enumerate(batch):
        if count % 16 == 0:
            verifier()
        cached = db.execute('SELECT 1 FROM pairs WHERE a=? AND b=? AND fa=? AND fb=?', (ka, kb, fa, fb)).fetchone()
        if not cached:
            score = -1 if fa == fb or text(a).casefold() == text(b).casefold() else cosine(va, vb)
            db.execute('INSERT OR REPLACE INTO pairs VALUES (?,?,?,?,?)', (ka, kb, fa, fb, score))
    db.commit()
    store.set('pairCursor', end)
    return end == total, end, total


def scores(store):
    yield from store.db.execute('SELECT a,b,score FROM pairs ORDER BY a,b')
