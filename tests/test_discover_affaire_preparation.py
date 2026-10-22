"""De la décision unique à la publication guidée, sans API ni moteur audio réels."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import discover_affaire_preparation as preparation
import discover_preparation
from manifeste_validation import valider_manifeste, valider_segments


class PreparationAffaireTests(unittest.TestCase):
    def test_source_une_decision_et_cache_local(self):
        decision = {'url': 'https://caselaw.nationalarchives.gov.uk/uksc/2024/1', 'text': 'Decision.'}
        item = {'source': {'url': decision['url']}}
        with tempfile.TemporaryDirectory() as root, patch('discover_affaire.recuperer_affaire', return_value=decision) as lire:
            for _ in range(2):
                source = preparation.preparer_source(item, root, lambda _: None, lambda: None)
                self.assertEqual(json.loads(Path(source['affaireFile']).read_text()), decision)
            lire.assert_called_once_with(decision['url'])

    def test_publication_kokoro_deux_voix_guide_dictee_verdict_et_licence(self):
        url = 'https://caselaw.nationalarchives.gov.uk/uksc/2024/1'
        histoire = {'title': 'A disputed contract', 'story_paragraphs': [
            {'speaker': 'Narrator', 'text': 'The buyer asked the seller to explain the contract.'},
            {'speaker': 'Guest', 'text': 'The seller disagreed about the terms of the contract.'}],
            'question': 'What should the court decide?', 'choices': ['Allow', 'Dismiss', 'Remit', 'Stay'],
            'verdict': 3, 'verdict_explanation_fr': 'La cour suspend la procédure.'}
        client = Mock(appels=[])
        client.statistiques.return_value = {}
        speech = Mock(provider='kokoro')
        speech.kokoro_speeds.return_value = {'af_bella': 1, 'bm_george': 1}
        def generate(segments, folder, name, verifier, speeds):
            self.assertEqual([s['speaker'] for s in segments], ['Narrator', 'Guest'])
            mp3, timings = Path(folder) / 'en.mp3', Path(folder) / 'timings.json'
            mp3.write_bytes(b'ID3-test')
            timings.write_text(json.dumps([{'id': s['id'], 'startMs': i * 1000, 'endMs': (i + 1) * 1000} for i, s in enumerate(segments)]))
            return {'file': str(mp3), 'timingsFile': str(timings), 'durationMs': 2000, 'origin': 'kokoro', 'timingSource': 'kokoro'}
        speech.generate.side_effect = generate
        def guide(client, segments, passage, niveau, voix, config):
            return {'level': niveau, 'voice': voix, 'passage': passage,
                    'expressions': [{'segmentId': segments[0]['id'], 'text': 'buyer', 'note': 'Acheteur'}], 'listening': []}, []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            affaire = root / 'affaire.json'
            affaire.write_text(json.dumps({'url': url, 'text': 'Judgment.', 'licence': 'Open Justice Licence'}))
            item = {'kind': 'affaire', 'ref': url, 'source': {'kind': 'affaire', 'url': url, 'language': 'en', 'title': 'Affaire'},
                    'options': {'coverage': 'guided', 'level': 'B1', 'style': 'narration', 'targetMinutes': None, 'faithful': False, 'keepOriginalCopy': False}}
            published = []
            with patch('discover_histoire.generer_histoire', return_value=histoire), \
                 patch('discover_guide.traduire_vers_francais', side_effect=lambda c, seg, etape: {s['id']: 'Traduction française.' for s in seg}), \
                 patch('discover_guide.generer_guide', side_effect=guide), \
                 patch('discover_speech.Session', return_value=speech) as session, \
                 patch('discover_cible.requete', side_effect=discover_preparation.discover_cible.ErreurDiscover(404, 'not_found')), \
                 patch('discover_cible.publier_manifeste', side_effect=lambda m, p, **k: published.append((m, p)) or {'status': 'ready'}), \
                 patch('discover_costs.enregistrer'):
                discover_preparation.preparer(item, {'affaireFile': str(affaire)}, root, lambda _: None, lambda: None,
                                             {'tts': {'provider': 'deepgram'}}, client)
            self.assertEqual(session.call_args.args[2]['tts']['provider'], 'kokoro')
            manifest, paths = published[0]
            valider_manifeste(manifest)
            self.assertEqual(manifest['content']['sourceType'], 'affaire')
            self.assertEqual(manifest['content']['licence'], 'Open Justice Licence')
            self.assertEqual(manifest['content']['sourceRef'], 'affaire:' + url)
            self.assertNotIn('audio', manifest['variants'][0])
            variant = manifest['variants'][1]
            self.assertEqual(variant['judgment']['verdict'], 3)
            self.assertNotIn('quiz', variant)
            doc = json.loads(Path(paths[variant['segmentsFile']]).read_text())
            self.assertEqual(len(doc['guide']['dictation']), 2)
            self.assertNotIn('verdict', json.dumps(doc))
            valider_segments(doc, variant, {s['id'] for s in json.loads(Path(paths[manifest['variants'][0]['segmentsFile']]).read_text())['segments']})
