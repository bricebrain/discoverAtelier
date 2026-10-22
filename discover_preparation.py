"""Chaîne complète de préparation d'un épisode sous le bail renouvelé de l'Atelier."""
import json
from pathlib import Path

import adaptation
from discover_citations import nettoyer_segments
import discover_audio
import discover_speech
import discover_cible
import discover_dictee
import discover_guide
import discover_source
import discover_englishfluency
import discover_quiz
import discover_costs
import discover_review
import discover_vocabulary
import pipeline
from discover_ai import Client, empreinte
from discover_evaluation import evaluer, valider_script
from discover_podcast_bundle import construire, content_id as identifiant_contenu, variant_key

# Au-delà, la voix est faite localement par Kokoro (aucun coût Deepgram) et le plafond Gemini suit la longueur.
LONG_SOURCE_MINUTES = 30


def source_minutes(sources):
    return max((s.get('endMs') or 0 for s in sources), default=0) / 60_000


def preparer_guide(item, source, root, folder, etape, verifier, config, client):
    """Original guidé, plus un guide sur un passage. Trois cas, sans jamais réécrire l'anglais :
    vidéo anglaise (l'original tel quel), texte anglais (lu tel quel par une voix), source française
    (traduite en anglais naturel et lue en entier)."""
    doc = json.loads(Path(source['segmentsFile']).read_text())
    sources, niveau = doc['segments'], item['options']['level']
    if not sources:
        raise discover_source.SourceRefusee('Original guidé : la source ne contient aucun texte.')
    langue = (doc.get('language') or item['source'].get('language') or 'en')[:2]
    horodatee = bool(source.get('audioFile')) and all(s.get('startMs') is not None for s in sources)
    words = sum(len(s['text'].split()) for s in sources)
    if isinstance(getattr(client, 'max_calls', None), int):
        client.max_calls = max(client.max_calls, words // 300 + 10)
        client.max_tokens = max(client.max_tokens, words * 20)
    francais, anglais, audio_anglais = None, None, None
    if langue == 'en' and horodatee:
        francais = discover_guide.traduire_vers_francais(client, sources, etape)
        segments_guide, voix, cible = sources, 'original', 'source'
    else:
        if langue == 'en':  # texte anglais : lu tel quel, traduction française à la demande
            francais = discover_guide.traduire_vers_francais(client, sources, etape)
            anglais = [{'id': s['id'], 'text': s['text'], 'fr': francais[s['id']], 'speaker': 'Narrator',
                        'sourceSegments': [s['id']]} for s in sources]
            cible = 'adaptation'
        else:
            anglais = pipeline.lire_json(str(folder / 'guided-english.json')) or discover_guide.traduire_vers_anglais(client, sources, etape)
            cible = 'faithful'
        anglais = nettoyer_segments(anglais, {s['id'] for s in sources})
        pipeline.ecrire_json(str(folder / 'guided-english.json'), anglais)
        minutes = source_minutes(sources)
        speech = discover_speech.Session([anglais], root.parent, config, folder, item['source'].get('title', ''),
                                         long_minutes=minutes if minutes > LONG_SOURCE_MINUTES else None)
        etape('tts')
        speeds = speech.kokoro_speeds(verifier) if speech.provider == 'kokoro' else {}
        audio_anglais = speech.generate(anglais, folder, 'en-faithful', verifier, speeds)
        timings = {t['id']: t for t in json.loads(Path(audio_anglais['timingsFile']).read_text())}
        segments_guide = [{**s, 'startMs': timings[s['id']]['startMs'], 'endMs': timings[s['id']]['endMs']} for s in anglais]
        voix = 'synthetic'
    verifier()
    etape('guide')
    passage = discover_guide.choisir_passage(client, segments_guide, niveau)
    guide, quiz = discover_guide.generer_guide(client, segments_guide, passage, niveau, voix, config)
    debut, fin = discover_guide.valider_passage(segments_guide, passage['fromSegment'], passage['toSegment'])
    dictee = discover_dictee.unites(segments_guide[debut:fin + 1])
    if dictee:
        guide['dictation'] = dictee
    pipeline.ecrire_json(str(folder / 'guide.json'), {'guide': guide, 'quiz': quiz, 'generation': client.statistiques()})
    verifier()
    etape('publish')
    content_id = identifiant_contenu(item)
    try:
        previous = discover_cible.requete(config, 'GET', '/atelier/contents/' + content_id + '/manifest')['manifest']
    except discover_cible.ErreurDiscover as e:
        if e.status != 404:
            raise
        previous = None
    extras = {'target': cible, 'guide': guide, 'quiz': quiz, 'fr': francais if cible == 'source' else None}
    if cible == 'adaptation':
        # Texte anglais lu tel quel : publié comme version « intégrale non simplifiée » de la source écrite.
        lu = {**item, 'options': {**item['options'], 'coverage': 'full', 'level': 'original', 'style': 'narration', 'targetMinutes': None}}
        prepared = {'script': {'segments': anglais, 'keyVocab': []}, 'evaluation': {'verdict': 'ok'}, 'generation': client.statistiques()}
        manifest, paths = construire(lu, source, prepared, audio_anglais, folder / 'publication', previous=previous, guide=extras)
    else:
        manifest, paths = construire(item, source, None, None, folder / 'publication', anglais, audio_anglais, previous, guide=extras)
    result = discover_cible.publier_manifeste(manifest, paths, config=config, demande=item, verifier=verifier)
    pipeline.ecrire_json(str(folder / 'published.json'), result)
    try:  # comptabilité locale : une publication réussie ne doit pas échouer pour un problème de coûts
        discover_costs.enregistrer(item, client.appels, folder, root.parent, config)
    except Exception as erreur:
        print('Coûts de la préparation non enregistrés : ' + str(erreur)[:200])
    return result


def preparer(item, source, root, etape, verifier, config, client=None):
    root = Path(root)
    folder = root / ('prepared-' + empreinte(item['options'])[:16])
    folder.mkdir(parents=True, exist_ok=True)
    client = client or Client(root / 'gemini-cache', verifier)
    if item['options'].get('coverage') == 'guided':
        return preparer_guide(item, source, root, folder, etape, verifier, config, client)
    # Les phrases d'origine ne servent qu'à la dictée du guide : jamais envoyées au modèle.
    sources = [{k: v for k, v in s.items() if k != 'phrases'} for s in json.loads(Path(source['segmentsFile']).read_text())['segments']]
    # Dossier : le modèle voit chaque passage avec le titre de sa source, sans la provenance (réservée au manifeste).
    dossier = item['source'].get('kind') == 'dossier'
    if dossier:
        sources = [{k: s[k] for k in ('id', 'text', 'source') if k in s} for s in sources]
    revision = (pipeline.lire_json(str(folder / 'revision.json')) or {}).get('revision', 0)
    minutes = source_minutes(sources)
    words = sum(len(s['text'].split()) for s in sources)
    if isinstance(getattr(client, 'max_calls', None), int):  # client réel (les tests passent parfois un faux)
        client.max_calls = max(client.max_calls, words // 60)
        client.max_tokens = max(client.max_tokens, words * 50)
    frequent = discover_vocabulary.charger(root.parent)
    edited = pipeline.lire_json(str(folder / 'edited.json'))
    contexte = adaptation.contexte_note(item['source'])  # article attribué à sa publication, ou note personnelle
    prepared = adaptation.generer(client, sources, item['options'], etape, revision=revision, frequent=frequent, dossier=dossier, contexte=contexte)
    # Une contradiction ou promotion détectée par le juge déclenche une nouvelle écriture, une fois.
    if prepared['evaluation']['verdict'] == 'rejected' and not edited:
        prepared = adaptation.generer(client, sources, item['options'], etape, revision=revision, frequent=frequent, feedback=prepared['evaluation']['judge'], dossier=dossier, contexte=contexte)
    if edited:
        edited = {**edited, 'segments': nettoyer_segments(edited['segments'], {s['id'] for s in sources})}
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
        faithful = nettoyer_segments(faithful, {s['id'] for s in sources})
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
    prepared['quiz'] = discover_quiz.generer(client, prepared['script'], item['options']['level'], config)
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
    speech = discover_speech.Session([prepared['script']['segments']] + ([faithful] if faithful else []),
                                     root.parent, config, folder, item['source'].get('title', ''),
                                     long_minutes=minutes if minutes > LONG_SOURCE_MINUTES else None)
    etape('tts')
    speeds = speech.kokoro_speeds(verifier) if speech.provider == 'kokoro' else {}
    audio = speech.generate(prepared['script']['segments'], folder, variant_key(item['options']), verifier, speeds)
    target = item['options']['targetMinutes']
    actual = audio['durationMs'] / 60_000
    if speech.provider == 'kokoro' and target and not .8 * target <= actual <= 1.2 * target:
        speeds = speeds or speech.kokoro_speeds(verifier)
        adjusted = {voice: round(min(1.4, max(.6, speed * actual / target)), 3) for voice, speed in speeds.items()}
        audio = speech.generate(prepared['script']['segments'], folder, variant_key(item['options']), verifier, adjusted)
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
        faithful_audio = speech.generate(faithful, folder, 'en-faithful', verifier, speeds)
    verifier()
    etape('publish')
    content_id = identifiant_contenu(item)
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
    try:  # comptabilité locale : une publication réussie ne doit pas échouer pour un problème de coûts
        discover_costs.enregistrer(item, client.appels, folder, root.parent, config)
    except Exception as erreur:
        print('Coûts de la préparation non enregistrés : ' + str(erreur)[:200])
    try:  # Destination indépendante, après clôture du bail Discover ; reprise sans ce bail.
        bridge = discover_englishfluency.publier(manifest, paths, variant_key(item['options']), folder, config)
        if bridge['status'] == 'failed':
            print('Discover publié ; envoi EnglishFluency à reprendre localement.')
    except Exception:
        print('Discover publié ; pont EnglishFluency indisponible. Vérifier configuration et fichiers locaux.')
    return result
