"""Relecture explicite, liée au texte exact, aux options et aux sources de la demande."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pipeline
from discover_ai import empreinte
from discover_evaluation import valider_script


class RelectureRequise(RuntimeError):
    pass


def signature(item, prepared, source):
    return empreinte({'id': item['id'], 'options': item['options'], 'script': prepared['script'], 'faithful': prepared.get('faithful'),
                       'evaluation': {k: v for k, v in prepared['evaluation'].items() if k not in ('acceptedByUser', 'reviewedAt', 'actualDurationMs')},
                       'source': source['segmentsSha256']})


def exiger(item, prepared, source, folder, automatique=True):
    """Version signalée par le contrôle : publiée automatiquement (défaut, `autoPublish` dans
    config_discover.json) et marquée « autoPublished » ; ou bloquée pour relecture si `autoPublish: false`."""
    if prepared['evaluation']['verdict'] == 'ok':
        return
    folder = Path(folder)
    review = {'id': item['id'], 'title': item['source']['title'], 'options': item['options'],
              'signature': signature(item, prepared, source), 'prepared': prepared,
              'sources': [{k: v for k, v in s.items() if k != 'phrases'}
                          for s in json.loads(Path(source['segmentsFile']).read_text())['segments']]}
    pipeline.ecrire_json(str(folder / 'review.json'), review)
    if automatique:
        # Le rapport reste consultable dans l'Atelier ; Discover affiche la version « non relue ».
        prepared['evaluation']['autoPublished'] = True
        return
    approved = pipeline.lire_json(str(folder / 'approval.json'))
    if prepared['evaluation']['verdict'] == 'review' and approved and approved.get('signature') == review['signature']:
        prepared['evaluation'].update(acceptedByUser=True, reviewedAt=approved['at'])
        return
    (folder / 'action.json').unlink(missing_ok=True)
    raise RelectureRequise('Version à relire dans l’Atelier avant publication.')


def trouver(root, identifiant):
    if not re.fullmatch(r'[0-9a-f-]{36}', identifiant):
        raise ValueError('Demande invalide.')
    for path in Path(root).glob('*/prepared-*/review.json'):
        review = pipeline.lire_json(str(path))
        if review and review.get('id') == identifiant:
            return path, review
    raise ValueError('Relecture introuvable.')


def liste(root, publiees=False):
    """Versions signalées : en attente de relecture, ou (publiees=True) déjà publiées automatiquement."""
    result = []
    for path in Path(root).glob('*/prepared-*/review.json'):
        data = pipeline.lire_json(str(path))
        if data and (path.parent / 'published.json').exists() == publiees:
            result.append({'id': data['id'], 'title': data['title'], 'verdict': data['prepared']['evaluation']['verdict'],
                           'signature': data['signature'], 'episode': path.parent.parent.name})
    return result


def action(root, body):
    path, review = trouver(root, body.get('id', ''))
    if body.get('signature') != review['signature']:
        raise ValueError('La version a changé. Recharger la relecture.')
    action = body.get('action')
    if action == 'approve':
        if review['prepared']['evaluation']['verdict'] != 'review':
            raise ValueError('Une version rejetée doit être régénérée ou corrigée.')
        pipeline.ecrire_json(str(path.parent / 'approval.json'), {'signature': review['signature'],
                              'at': datetime.now(timezone.utc).isoformat()})
    elif action == 'edit':
        script = review['prepared']['script'] | {'segments': body.get('segments')}
        if not isinstance(script['segments'], list) or not script['segments'] or len(script['segments']) > 1000:
            raise ValueError('Segments corrigés invalides.')
        import jsonschema
        from discover_adaptation_schema import SCRIPT
        jsonschema.validate(script, SCRIPT)
        valider_script(script, {s['id'] for s in review['sources']}, review['options']['style'])
        target = review['options'].get('targetMinutes')
        if target:
            from discover_evaluation import mots
            count = sum(len(mots(s['text'])) for s in script['segments'])
            words = round(target * review['prepared']['generation'].get('wordsPerMinute', 130))
            if not .8 * words <= count <= 1.2 * words:
                raise ValueError(f'La correction doit rester entre {round(.8*words)} et {round(1.2*words)} mots.')
        mapped = None
        if body.get('faithful') is not None:
            faithful = body['faithful']
            expected = review['prepared'].get('faithful') or []
            if not isinstance(faithful, list) or len(faithful) != len(expected) or [s.get('id') for s in faithful] != [s['id'] for s in expected]:
                raise ValueError('La traduction fidèle doit conserver chaque identifiant, dans le même ordre.')
            mapped = []
            for changed, original in zip(faithful, expected):
                if not isinstance(changed.get('text'), str) or not changed['text'].strip() or len(changed['text']) > 20000:
                    raise ValueError('Traduction fidèle invalide.')
                mapped.append({**original, 'text':changed['text']})
        pipeline.ecrire_json(str(path.parent / 'edited.json'), script)
        if mapped is not None:
            pipeline.ecrire_json(str(path.parent / 'edited-faithful.json'), mapped)
    elif action == 'regenerate':
        old = pipeline.lire_json(str(path.parent / 'revision.json')) or {'revision': 0}
        pipeline.ecrire_json(str(path.parent / 'revision.json'), {'revision': old['revision'] + 1})
        (path.parent / 'edited.json').unlink(missing_ok=True)
        (path.parent / 'edited-faithful.json').unlink(missing_ok=True)
        (path.parent / 'approval.json').unlink(missing_ok=True)
    else:
        raise ValueError('Action de relecture inconnue.')
    pipeline.ecrire_json(str(path.parent / 'action.json'), {'id': review['id']})
    return {'ok': True}


def suivante(root):
    for path in sorted(Path(root).glob('*/prepared-*/action.json')):
        action = pipeline.lire_json(str(path))
        if action:
            return action['id'], path
    return None, None
