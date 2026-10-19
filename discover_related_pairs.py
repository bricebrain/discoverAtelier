"""Calcul incrémental des cosinus : chaque élément n'est comparé qu'une fois aux autres, seules les paires proches sont gardées.

Le Mac de l'utilisateur calcule sur le processeur seul : comparer toutes les paires à chaque passage (n²/2) devient vite
trop long. Un nouvel élément est comparé une fois à tous les éléments déjà traités ; les paires sous le plancher (voisins,
zone douteuse) ne servent à rien et ne sont pas stockées. Les vecteurs sont normalisés une fois : cosinus = produit scalaire.
"""
import math

from discover_related_similarity import text


def plancher(config):
    return min(config.get('relatedMinScore', .55), config.get('relatedDoubtScore', .60), config.get('relatedCrossLanguageScore', .64))


def _unit(vector):
    norm = math.sqrt(math.sumprod(vector, vector)) if vector else 0
    return [x / norm for x in vector] if norm else None


def prepare(store, rows, verifier, limit=2_000_000, config=None):
    """Compare les éléments pas encore traités ; `limit` borne le nombre de comparaisons d'un passage (reprise ensuite).

    Renvoie (terminé, éléments traités, éléments au total)."""
    db, floor = store.db, plancher(config or {})
    db.execute('''CREATE TABLE IF NOT EXISTS near_pairs (
        fa TEXT NOT NULL, fb TEXT NOT NULL, score REAL NOT NULL, PRIMARY KEY(fa, fb))''')
    db.execute('CREATE TABLE IF NOT EXISTS pair_done (f TEXT PRIMARY KEY)')
    db.execute('DROP TABLE IF EXISTS pairs')  # ancien stockage de toutes les paires
    done = {f for (f,) in db.execute('SELECT f FROM pair_done')}
    unique = {}
    for _, item, f, vector in rows:
        unique.setdefault(f, (item, vector))
    known = [(f, _unit(v), text(i).casefold()) for f, (i, v) in unique.items() if f in done]
    known = [k for k in known if k[1] is not None]
    todo = [f for f in unique if f not in done]
    budget, sumprod = limit, math.sumprod
    for f in todo:
        item, vector = unique[f]
        unit, body = _unit(vector), text(item).casefold()
        if unit is not None:
            if known and budget < len(known):
                break
            verifier()
            for g, other, other_body in known:
                if body == other_body:
                    continue
                score = sumprod(unit, other)
                if score >= floor:
                    a, b = (f, g) if f < g else (g, f)
                    db.execute('INSERT OR REPLACE INTO near_pairs VALUES (?,?,?)', (a, b, min(1.0, score)))
            budget -= len(known)
            known.append((f, unit, body))
        db.execute('INSERT OR IGNORE INTO pair_done VALUES (?)', (f,))
        done.add(f)
    db.commit()
    total = len(unique)
    processed = sum(1 for f in unique if f in done)
    return processed == total, processed, total


def scores(store, rows):
    """Paires proches entre les éléments actuels, sous la forme (clé a, clé b, score) attendue par le calcul des groupes."""
    keys = {}
    for k, _, f, _ in rows:
        keys.setdefault(f, []).append(k)
    for fa, fb, score in store.db.execute('SELECT fa, fb, score FROM near_pairs ORDER BY fa, fb'):
        for ka in keys.get(fa, ()):
            for kb in keys.get(fb, ()):
                if ka != kb:
                    yield ka, kb, score
