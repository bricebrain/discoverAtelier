"""Préparation à la demande d’une décision : histoire auditée, voix Kokoro et verdict différé."""
import json
from pathlib import Path

import discover_affaire
import discover_histoire
import discover_source
import pipeline
from discover_ai import empreinte


def preparer_source(item, dossier, etape, verifier):
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / 'affaire.json'
    verifier()
    if not fichier.exists():
        etape('download')
        decision = discover_affaire.recuperer_affaire(item['source']['url'])
        pipeline.ecrire_json(str(fichier), decision)
    verifier()
    return {'affaireFile': str(fichier), 'audioFile': None,
            'source': {'kind': 'affaire', 'language': 'en', 'title': 'À vous de juger'}}


def preparer(item, source, root, folder, etape, verifier, config, client):
    from discover_preparation import preparer_guide
    decision = json.loads(Path(source['affaireFile']).read_text())
    niveau = item['options']['level']
    etape('adapt')
    histoire = discover_histoire.generer_histoire(client, decision, niveau, config)
    verifier()
    pipeline.ecrire_json(str(folder / 'histoire.json'), histoire)
    segments = []
    for paragraphe in histoire['story_paragraphs']:
        for texte in discover_source.decouper_texte(paragraphe['text']):
            segments.append({'id': f's{len(segments) + 1:04d}', 'text': texte,
                             'speaker': paragraphe['speaker'], 'startMs': None, 'endMs': None})
    fichier = folder / 'segments-source.json'
    pipeline.ecrire_json(str(fichier), {'language': 'en', 'timingSource': 'none', 'segments': segments})
    demande = {**item, 'source': {**item['source'], 'title': histoire['title'], 'url': decision['url'],
                                 'language': 'en', 'licence': decision['licence']}}
    origine = {**source, 'segmentsFile': str(fichier), 'judgment': {
        'question': histoire['question'], 'choices': histoire['choices'], 'verdict': histoire['verdict'],
        'verdictExplanationFr': histoire['verdict_explanation_fr']}}
    configuration = {**config, 'comprehensionQuiz': False, 'tts': {**config.get('tts', {}), 'provider': 'kokoro'}}
    return preparer_guide(demande, origine, root, folder, etape, verifier, configuration, client)
