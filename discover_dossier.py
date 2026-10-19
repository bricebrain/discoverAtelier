"""Dossier multisource (chantier A) : chaque source est préparée avec la chaîne existante, puis les passages sont
assemblés en une source commune dont chaque passage garde sa provenance (source et instant dans l'original)."""
import json
import re
from pathlib import Path

import discover_source
import pipeline
from discover_ai import empreinte

MOTIF_EPISODE = re.compile(r'[0-9a-f]{20}')
MOTIF_VIDEO = re.compile(r'[A-Za-z0-9_-]{11}')
MOTIF_NOTE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def _dossier_cache(root, snapshot):
    """Même dossier de travail que la préparation de cette source seule : transcription jamais refaite."""
    root = Path(root)
    if snapshot['kind'] == 'youtube':
        if not MOTIF_VIDEO.fullmatch(snapshot.get('videoId') or ''):
            raise ValueError('Identifiant vidéo invalide dans le dossier.')
        return root / ('youtube-' + snapshot['videoId'])
    if snapshot['kind'] == 'article':
        if not MOTIF_EPISODE.fullmatch(snapshot['ref']):
            raise ValueError('Identifiant d’article invalide dans le dossier.')
        return root / ('article-' + snapshot['ref'])
    if snapshot['kind'] == 'reflection':
        if not MOTIF_NOTE.fullmatch(snapshot['ref']):
            raise ValueError('Identifiant de note invalide dans le dossier.')
        return root / ('reflection-' + snapshot['ref'])
    if not MOTIF_EPISODE.fullmatch(snapshot['ref']):
        raise ValueError('Identifiant d’épisode invalide dans le dossier.')
    return root / snapshot['ref']


def etiquette(snapshot):
    """Libellé d'une source pour le modèle : un article est attribué à son journal, une note reste personnelle."""
    title = snapshot['title'][:160]
    if snapshot['kind'] == 'article' or (snapshot['kind'] == 'reflection' and snapshot.get('origin') == 'article'):
        return f"{title} (article, {(snapshot.get('sourceName') or 'publication inconnue')[:80]})"
    if snapshot['kind'] == 'reflection':
        return f'{title} (personal note)'
    return title


def _segments_source(snapshot, root, options, etape, verifier):
    """Passages d'une source : (segments, langue, empreinte du texte utilisé)."""
    kind = snapshot['kind']
    if kind == 'content':
        segments = [{'id': s['id'], 'text': s['text'], 'startMs': s.get('startMs'), 'endMs': s.get('endMs')}
                    for s in snapshot.get('segments') or [] if (s.get('text') or '').strip()]
        language = snapshot.get('language') or 'en'
    else:
        sub = {'ref': snapshot['ref'], 'options': options, 'source': {**snapshot, 'kind': kind}}
        if kind in ('reflection', 'article'):
            if kind == 'article' and snapshot.get('contentStatus') != 'complete':
                raise ValueError('Le dossier attend le texte complet de l’article.')
            resultat = discover_source.preparer_texte(sub, _dossier_cache(root, snapshot), etape, verifier)
        elif kind == 'youtube':
            resultat = discover_source.preparer_youtube(sub, _dossier_cache(root, snapshot), etape, verifier)
        else:
            resultat = discover_source.preparer(sub, _dossier_cache(root, snapshot), etape, verifier)
        doc = json.loads(Path(resultat['segmentsFile']).read_text())
        segments = doc['segments']
        language = doc.get('language') or (resultat.get('source') or {}).get('language') or 'en'
    if not segments:
        raise RuntimeError('Une source du dossier ne contient aucun passage exploitable : ' + snapshot['title'][:80])
    return segments, language[:2], empreinte([s['text'] for s in segments])


def langue_majoritaire(segments):
    compte = {}
    for s in segments:
        compte[s['language']] = compte.get(s['language'], 0) + len(s['text'].split())
    return max(compte, key=compte.get) if compte else 'en'


def preparer(item, dossier, etape, verifier, root=None):
    """Prépare toutes les sources de l'exécution figée par le Worker, dans l'ordre d1…d6."""
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    root = Path(root) if root else dossier.parent
    snapshots = item['source'].get('sources') or []
    if not 2 <= len(snapshots) <= 6 or [s['id'] for s in snapshots] != [f'd{i}' for i in range(1, len(snapshots) + 1)]:
        raise ValueError('Sources du dossier invalides.')
    combined, summaries = [], []
    for snapshot in snapshots:
        verifier()
        segments, language, sha = _segments_source(snapshot, root, item['options'], etape, verifier)
        for s in segments:
            combined.append({'id': f"{snapshot['id']}-{s['id']}", 'text': s['text'], 'startMs': None, 'endMs': None,
                             'source': etiquette(snapshot), 'language': language,
                             'provenance': {'sourceId': snapshot['id'], 'segmentId': s['id'],
                                            'startMs': s.get('startMs'), 'endMs': s.get('endMs')}})
        titre = snapshot['title'][:400]
        if (snapshot['kind'] == 'article' or snapshot.get('origin') == 'article') and snapshot.get('sourceName'):
            titre = f"{snapshot['sourceName'][:80]} · {titre}"
        summary = {'id': snapshot['id'], 'type': snapshot['type'], 'ref': snapshot['ref'], 'title': titre,
                   'capturedAt': snapshot['capturedAt'], 'sha256': sha}
        if snapshot.get('publicationId'):
            summary.update(publicationId=snapshot['publicationId'], variantKey=snapshot['variantKey'])
        summaries.append(summary)
    language = langue_majoritaire(combined)
    segments_path = dossier / 'segments-source.json'
    pipeline.ecrire_json(str(segments_path), {'language': language, 'timingSource': 'none',
                                              'segments': [{k: v for k, v in s.items() if k != 'language'} for s in combined]})
    resultat = {'segmentsFile': str(segments_path), 'segmentsSha256': empreinte(segments_path.read_text()), 'audioFile': None,
                'timingSource': 'none', 'options': item['options'],
                'source': {'title': item['source'].get('title') or 'Dossier', 'language': language, 'kind': 'dossier'},
                'dossierSources': summaries}
    pipeline.ecrire_json(str(dossier / 'source.json'), resultat)
    verifier()
    return resultat
