"""Chaîne complète de préparation d'un épisode sous le bail renouvelé de l'Atelier."""
import json
from pathlib import Path

import adaptation
import discover_audio
import discover_cible
import discover_review
import discover_vocabulary
import pipeline
from discover_ai import Client, empreinte
from discover_evaluation import evaluer, valider_script
from discover_podcast_bundle import construire, variant_key


def preparer(item, source, root, etape, verifier, config, client=None):
    root = Path(root)
    folder = root / ('prepared-' + empreinte(item['options'])[:16])
    folder.mkdir(parents=True, exist_ok=True)
    client = client or Client(root / 'gemini-cache', verifier)
    sources = json.loads(Path(source['segmentsFile']).read_text())['segments']
    revision = (pipeline.lire_json(str(folder / 'revision.json')) or {}).get('revision', 0)
    frequent = discover_vocabulary.charger(root.parent)
    edited = pipeline.lire_json(str(folder / 'edited.json'))
    prepared = adaptation.generer(client, sources, item['options'], etape, revision=revision, frequent=frequent)
    # Une contradiction ou promotion détectée par le juge déclenche une nouvelle écriture, une fois.
    if prepared['evaluation']['verdict'] == 'rejected' and not edited:
        prepared = adaptation.generer(client, sources, item['options'], etape, revision=revision, frequent=frequent, feedback=prepared['evaluation']['judge'])
    if edited:
        valider_script(edited, {s['id'] for s in sources}, item['options']['style'])
        prepared['script'] = edited
        prepared['evaluation'] = adaptation.juger_script(client, edited, sources, item['options'], prepared['facts'], frequent)
    prepared['script']['segments'] = [{**s, 'id': f'p{i:04d}'} for i, s in enumerate(prepared['script']['segments'], 1)]
    # Le schéma Gemini n'expose pas les IDs : retirer ceux ajoutés avant une éventuelle édition.
    if edited and any('id' in s for s in edited['segments']):
        raise ValueError('Les IDs des paragraphes corrigés sont calculés par l’Atelier.')
    faithful, faithful_audio = None, None
    if item['options']['faithful']:
        faithful = pipeline.lire_json(str(folder / 'edited-faithful.json')) or adaptation.traduire_fidele(client, sources, etape, revision=revision)
        faithful_judge = adaptation.juger_fidele(client, sources, faithful)
        prepared['faithful'] = faithful
        prepared['evaluation']['faithfulJudge'] = faithful_judge
        if faithful_judge['verdict'] != 'ok' or any(faithful_judge[k] for k in ('unsupportedClaims', 'omittedKeyPoints', 'lostNuances')):
            if faithful_judge['verdict'] == 'rejected':
                prepared['evaluation']['verdict'] = 'rejected'
            elif prepared['evaluation']['verdict'] != 'rejected':
                prepared['evaluation']['verdict'] = 'review'
        faithful_checks = evaluer({'segments':faithful,'tooShortForSubject':False,'recommendedMinutes':None}, sources, {'level':'original'})
        prepared['evaluation']['faithfulChecks'] = {key:faithful_checks[key] for key in ('numbersMissingFromSource','entitiesMissingFromSource')}
        if any(prepared['evaluation']['faithfulChecks'].values()) and prepared['evaluation']['verdict'] != 'rejected':
            prepared['evaluation']['verdict'] = 'review'
    prepared['generation'] = {**prepared['generation'], **client.statistiques()}
    runtime = pipeline.lire_json(str(folder / 'runtime.json'))
    if runtime and runtime.get('scriptHash') == empreinte(prepared['script']) and item['options']['targetMinutes']:
        target = item['options']['targetMinutes']
        actual = runtime['durationMs'] / 60_000
        if not .8 * target <= actual <= 1.2 * target:
            prepared['evaluation'].update(verdict='review', durationOutsideTarget={'targetMinutes': target, 'actualMinutes': round(actual, 2)})
    pipeline.ecrire_json(str(folder / 'prepared.json'), prepared)
    automatique = bool(config.get('autoPublish', True))
    discover_review.exiger(item, prepared, source, folder, automatique)
    etape('tts')
    speeds = discover_audio.calibrer(root.parent / '.kokoro', verifier)
    audio = discover_audio.executer(prepared['script']['segments'], folder, variant_key(item['options']), verifier, speeds)
    target = item['options']['targetMinutes']
    actual = audio['durationMs'] / 60_000
    if target and not .8 * target <= actual <= 1.2 * target:
        adjusted = {voice: round(min(1.4, max(.6, speed * actual / target)), 3) for voice, speed in speeds.items()}
        audio = discover_audio.executer(prepared['script']['segments'], folder, variant_key(item['options']), verifier, adjusted)
        actual = audio['durationMs'] / 60_000
    pipeline.ecrire_json(str(folder / 'runtime.json'), {'scriptHash': empreinte(prepared['script']), 'durationMs': audio['durationMs']})
    if target and not .8 * target <= actual <= 1.2 * target:
        prepared['evaluation'].update(verdict='review', durationOutsideTarget={'targetMinutes': target, 'actualMinutes': round(actual, 2)})
        # Une approbation de texte ne vaut pas approbation d'une nouvelle durée hors cible.
        prepared['evaluation'].pop('acceptedByUser', None)
        prepared['evaluation'].pop('reviewedAt', None)
        discover_review.exiger(item, prepared, source, folder, automatique)
    prepared['evaluation']['actualDurationMs'] = audio['durationMs']
    if faithful:
        etape('tts')
        faithful_audio = discover_audio.executer(faithful, folder, 'en-faithful', verifier, speeds)
    verifier()
    etape('publish')
    content_id = 'podcast-' + item['ref']
    try:
        previous = discover_cible.requete(config, 'GET', '/atelier/contents/' + content_id + '/manifest')['manifest']
    except discover_cible.ErreurDiscover as e:
        if e.status != 404:
            raise
        previous = None
    manifest, paths = construire(item, source, prepared, audio, folder / 'publication', faithful, faithful_audio, previous)
    result = discover_cible.publier_manifeste(manifest, paths, config=config, demande=item, verifier=verifier)
    pipeline.ecrire_json(str(folder / 'published.json'), result)
    (folder / 'action.json').unlink(missing_ok=True)
    return result
