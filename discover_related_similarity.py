"""Fonctions pures : texte, cosinus, indices et composantes événementielles."""
import hashlib
import html
import math
import re
from datetime import datetime


def text(item):
    raw = (item.get('title') or '') + ' ' + (item.get('excerpt') or '')
    raw = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', raw, flags=re.I | re.S)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', raw))).strip()[:900]


def fingerprint(model, value):
    return hashlib.sha256((model + '\0' + value).encode()).hexdigest()


def cosine(a, b):
    if len(a) != len(b) or not a:
        return -1
    norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return max(-1, min(1, sum(x*y for x, y in zip(a, b)) / norm)) if norm else -1


def clues(value):
    tokens = re.findall(r"[\wÀ-ÿ]+|[.!?]", value)
    found, start = set(), True
    for token in tokens:
        if token in '.!?':
            start = True
            continue
        if token.isdigit() or (not start and token[0].isupper()):
            found.add(token.casefold())
        start = False
    return found


def within(a, b, hours):
    try:
        x, y = (datetime.fromisoformat(v['publishedAt'].replace('Z', '+00:00')) for v in (a, b))
        return abs((x-y).total_seconds()) <= hours * 3600
    except (KeyError, TypeError, ValueError):
        return False


def calculate(rows, config, judge, verifier=lambda: None, pairs=None):
    neighbors = {k: [] for k, _, _, _ in rows}
    parent = {k: k for k in neighbors}
    by_key = {k: i for k, i, _, _ in rows}
    centrality = {k: 0 for k in neighbors}
    def root(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    by_row = {k: (i, f) for k, i, f, _ in rows}
    if pairs is None:
        pairs = ((ka, kb, cosine(va, vb)) for pos, (ka, a, fa, va) in enumerate(rows)
                 for kb, b, fb, vb in rows[pos+1:] if fa != fb and text(a).casefold() != text(b).casefold())
    for index, (ka, kb, score) in enumerate(pairs):
        if index % 16 == 0:
            verifier()
        a, fa = by_row[ka]
        b, fb = by_row[kb]
        if score < 0:
            continue
        if score >= config.get('relatedMinScore', .55):
            neighbors[ka].append({'targetType': b['type'], 'targetId': b['id'], 'score': round(score, 6)})
            neighbors[kb].append({'targetType': a['type'], 'targetId': a['id'], 'score': round(score, 6)})
        if not within(a, b, config.get('relatedWindowHours', 72)):
            continue
        same = a.get('language') == b.get('language') and a.get('language') not in (None, 'und')
        threshold = config.get('relatedSameLanguageScore', .72) if same else config.get('relatedCrossLanguageScore', .64)
        valid = score >= threshold and bool(clues(text(a)) & clues(text(b)))
        if not valid and score >= config.get('relatedDoubtScore', .60):
            valid = judge(a, b, fa, fb)
        if valid:
            parent[root(kb)] = root(ka)
            centrality[ka] += score
            centrality[kb] += score
    components = {}
    for k in parent:
        components.setdefault(root(k), []).append(k)
    groups = []
    for members in components.values():
        if len(members) < 2:
            continue
        central = max(members, key=lambda k: centrality[k])
        gid = hashlib.sha256('|'.join(sorted(members)).encode()).hexdigest()[:32]
        groups.append({'groupId': gid, 'members': [{'type': by_key[k]['type'], 'id': by_key[k]['id']} for k in members],
                       'title': (by_key[central].get('title') or '')[:300],
                       'dossierCandidate': len({by_key[k].get('publisher') for k in members if by_key[k].get('publisher')}) >= 2})
    sources = [{'type': i['type'], 'id': i['id'], 'neighbors': sorted(neighbors[k], key=lambda n: (-n['score'], n['targetType'], n['targetId']))[:5]}
               for k, i, _, _ in rows]
    return sources, groups
