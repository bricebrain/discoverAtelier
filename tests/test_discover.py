"""Fixtures partagées et publication Discover ; aucun accès réseau distant."""
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_cible
import discover_bundle
from manifeste_validation import contrats, valider_manifeste, valider_segments, ErreurManifeste
from test_pipeline import BaseBundle


class TestContratDiscover(unittest.TestCase):
    def test_fixtures_valides(self):
        for file in (contrats() / 'fixtures').glob('valid-*.json'):
            with self.subTest(file=file.name):
                valider_manifeste(json.loads(file.read_text()))

    def test_fixtures_invalides(self):
        cases = json.loads((contrats() / 'fixtures/invalid-manifests.json').read_text())
        for case in cases:
            with self.subTest(case=case['name']):
                with self.assertRaises(ErreurManifeste) as ctx:
                    valider_manifeste(case['manifest'], case.get('context'))
                self.assertEqual(ctx.exception.code, case['code'])

    def test_segments_invalides(self):
        cases = json.loads((contrats() / 'fixtures/invalid-segments.json').read_text())
        for case in cases:
            with self.subTest(case=case['name']):
                with self.assertRaises(ErreurManifeste) as ctx:
                    valider_segments(case['document'], case['variant'])
                self.assertEqual(ctx.exception.code, case['code'])

    def test_reprise_envoie_uniquement_les_manquants(self):
        m = json.loads((contrats() / 'fixtures/valid-youtube.json').read_text())
        path = next(iter(m['files']))
        with mock.patch.object(discover_cible, 'requete', side_effect=[
                {'publicationId': 'id', 'status': 'uploading', 'missing': [path]},
                {'ok': True}, {'publicationId': 'id', 'status': 'ready'}]) as request:
            result = discover_cible.publier_manifeste(m, {path: '/tmp/test.json'}, config={"workerUrl": "https://discover.example.com"})
        self.assertEqual(result['status'], 'ready')
        self.assertEqual([c.args[1] for c in request.call_args_list], ['POST', 'PUT', 'POST'])
        self.assertEqual(request.call_args_list[1].kwargs['fichier'], '/tmp/test.json')

    def test_deja_publie_sans_renvoi_ni_commit(self):
        m = json.loads((contrats() / 'fixtures/valid-youtube.json').read_text())
        with mock.patch.object(discover_cible, 'requete', return_value={
                'publicationId': 'id', 'status': 'ready'}) as request:
            discover_cible.publier_manifeste(m, {}, config={'workerUrl': 'https://discover.example.com'})
        self.assertEqual(request.call_count, 1)


class TestBundleDiscover(BaseBundle):
    def creer(self, slug, source, texte):
        import bundles
        segments = super().creer(slug, source, texte)
        meta = bundles.lire_meta(slug)
        meta['sourceUrl'] = 'https://www.youtube.com/watch?v=' + slug
        bundles.ecrire_meta(slug, meta)
        return segments

    def test_fr_source_et_fidele_gardees_sans_faux_b1(self):
        self.bundle_fr_complet('video-fr')
        self.generer_tts('video-fr')
        with mock.patch.object(discover_bundle.pipeline, 'duree_audio_secondes', return_value=12):
            m, paths = discover_bundle.construire('video-fr')
        self.assertEqual([v['kind'] for v in m['variants']], ['source', 'faithful_translation'])
        self.assertEqual([v['key'] for v in m['variants']], ['fr-source', 'en-faithful'])
        self.assertTrue(all(v['cefrLevel'] is None for v in m['variants']))
        for path, f in m['files'].items():
            self.assertEqual(discover_bundle.empreinte(paths[path]), f['sha256'])
        self.assertIn('audio/fr-source.mp3', paths)
        self.assertIn('audio/en-faithful.mp3', paths)

    def test_pas_de_pedagogie_requise_ni_duree_sans_audio(self):
        segments = self.creer('video-en', 'en', 'A source sentence.')
        discover_bundle.pipeline.enregistrer_traduction('video-en', self.traduction(segments, 'FR'))
        os.unlink(os.path.join(self.dossier, 'video-en.mp3'))
        m, _ = discover_bundle.construire('video-en')
        self.assertEqual(len(m['variants']), 2)
        self.assertTrue(all(not v.get('audio') for v in m['variants']))

    def test_manifeste_identique_sur_deux_constructions(self):
        self.bundle_fr_complet('stable-slug')
        with mock.patch.object(discover_bundle.pipeline, 'duree_audio_secondes', return_value=12):
            a, _ = discover_bundle.construire('stable-slug')
            b, _ = discover_bundle.construire('stable-slug')
        self.assertEqual(a, b)
