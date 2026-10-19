"""Passage de rapprochement inactif : Ollama local, aucun vecteur publié."""
import json
import logging
import math
import os
import time
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlencode

from discover_related_store import Store
import discover_related_pairs
from discover_related_similarity import calculate, fingerprint, text
from discover_related_judge import Judge

LOG = logging.getLogger(__name__)


def embed(texts, config):
    body = {'model': config.get('relatedModel', 'bge-m3'), 'input': texts, 'keep_alive': '2m',
            'options': {'num_thread': max(1, min(4, int(config.get('relatedThreads', 4))))}}
    req = urllib.request.Request('http://localhost:11434/api/embed', data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('Réponse Ollama trop volumineuse.')
    vectors = json.loads(raw)['embeddings']
    if len(vectors) != len(texts) or any(not v or len(v) > 8192 or
            any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in v) for v in vectors):
        raise ValueError('Vecteurs Ollama invalides.')
    return vectors


def status(root):
    store = Store(root)
    try:
        day = datetime.now(timezone.utc).date().isoformat()
        from discover_costs import Registre
        with Registre(root).connection() as costs:
            cost = costs.execute("SELECT coalesce(sum(gemini_micro+openai_micro),0) FROM preparations WHERE item_id LIKE 'related-%' AND substr(created_at,1,10)=?", (day,)).fetchone()[0] / 1_000_000
        return {'llmCostTodayUsd': cost, **store.get('status', {'ollama': 'Non testé', 'lastRun': None, 'groups': 0}),
                'encoded': store.db.execute('SELECT count(*) FROM vectors').fetchone()[0],
                'llmCallsToday': store.db.execute('SELECT count(*) FROM judgments WHERE day=?', (day,)).fetchone()[0]}
    finally:
        store.close()


def publish(store, config, request, sources, groups, verifier):
    current = {g['groupId'] for g in groups}
    previous = store.get('groups', [])
    groups = groups + [{'groupId': gid, 'members': [], 'title': '', 'dossierCandidate': False} for gid in previous if gid not in current]
    # Chaque source remplace ses cinq voisins dans une même requête.
    for offset in range(0, len(sources), 40):
        batch = [s for s in sources[offset:offset+40] if store.changed('source:'+s['type']+':'+s['id'], s)]
        if batch:
            verifier()
            request(config, 'POST', '/atelier/related', {'sources': batch, 'groups': []})
            for s in batch:
                store.ack('source:'+s['type']+':'+s['id'], s)
    for g in groups:
        if len(g['members']) > 100:
            raise ValueError('Groupe de plus de 100 membres : publication différée.')
        if store.changed('group:'+g['groupId'], g):
            verifier()
            request(config, 'POST', '/atelier/related', {'sources': [], 'groups': [g]})
            store.ack('group:'+g['groupId'], g)
    store.set('groups', sorted(current))


def run(root, config, request, busy=False, verifier=lambda: None, encoder=None, judge_factory=None, now=None):
    if busy:
        return {'skipped': 'Préparation en cours'}
    store = Store(root)
    now = time.time() if now is None else now
    try:
        if now - store.get('lastAttempt', 0) < 900:
            return {'skipped': 'Intervalle de 15 minutes'}
        store.set('lastAttempt', now)
        # Cette fonction s’exécute sur le thread du consommateur ; priorité abaissée une seule fois.
        if hasattr(os, 'nice'):
            try:
                if os.nice(0) < 5:
                    os.nice(5)
            except OSError:
                pass
        queue = request(config, 'GET', '/atelier/queue').get('items', [])
        if any(i.get('status') == 'leased' for i in queue):
            return {'skipped': 'Bail de préparation actif'}
        model = config.get('relatedModel', 'bge-m3')
        cursor = store.get('cursor', 0)
        page = request(config, 'GET', '/atelier/related/items?' + urlencode({'after': cursor, 'limit': 200}))
        for item in page['items']:
            store.put(item, fingerprint(model, text(item)))
        # Le curseur avance seulement après persistance locale ; l’encodage restant est reprenable.
        store.set('cursor', page['nextCursor'])
        rows = store.all()
        eligible = [(k, i, fingerprint(model, text(i))) for k, i, _ in rows
                    if config.get('relatedIncludeNotes', True) or i['type'] != 'reflection']
        pending = {}
        for _, i, f in eligible:
            if store.vector(f) is None:
                pending[f] = text(i)
        pending = list(pending.items())[:200]
        for offset in range(0, len(pending), 16):
            verifier()
            batch = pending[offset:offset+16]
            try:
                vectors = (encoder or embed)([v for _, v in batch], config)
                if len(vectors) != len(batch):
                    raise ValueError('Lot Ollama incomplet.')
            except Exception:
                message = 'Ollama indisponible : passage de rapprochement sauté, reprise au prochain passage.'
                LOG.warning(message)
                store.set('status', {**store.get('status', {}), 'ollama': message})
                return {'skipped': message}
            for (f, _), vector in zip(batch, vectors):
                store.save_vector(f, vector)
        ready = [(k, i, f, store.vector(f)) for k, i, f in eligible if store.vector(f) is not None]
        complete, done, total = discover_related_pairs.prepare(store, ready, verifier)
        if not complete:
            store.set('status', {**store.get('status', {}), 'ollama': 'Cache local · calcul des voisins',
                                 'pairsDone': done, 'pairsTotal': total})
            return {'deferred': 'Calcul des voisins reprenable', 'pairsDone': done, 'pairsTotal': total}
        sources, groups = calculate(ready, config, Judge(store, root, config, verifier, judge_factory),
                                    verifier, pairs=discover_related_pairs.scores(store))
        # Désactivation des notes : effacer également leurs anciens voisins distants.
        sources += [{'type': i['type'], 'id': i['id'], 'neighbors': []} for _, i, _ in rows
                    if i['type'] == 'reflection' and not config.get('relatedIncludeNotes', True)]
        publish(store, config, request, sources, groups, verifier)
        result = {'ollama': 'Disponible' if pending else 'Cache local',
                  'lastRun': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'groups': len(groups)}
        store.set('status', result)
        return result
    finally:
        store.close()
