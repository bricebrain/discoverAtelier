"""Coûts visibles dans l'Atelier : tarifs configurables, registre idempotent, totaux IA + Deepgram par mois."""
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover_costs
import discover_http
import discover_preparation as workflow
from discover_tts_budget import Budget

MAINTENANT = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
SEPTEMBRE = datetime(2026, 9, 30, 18, 30, tzinfo=timezone.utc)
# Jetons choisis pour des coûts ronds avec les tarifs par défaut (Gemini 0,20 / 0,80 ; gpt-5-mini 0,25 / 2).
APPELS = {
    'a': {'stage': 'plan', 'provider': 'gemini', 'model': 'gemini-3.1-flash-lite', 'inputTokens': 1_000_000, 'outputTokens': 500_000},
    'b': {'stage': 'adapt', 'provider': 'gemini', 'model': 'gemini-3.1-flash-lite', 'inputTokens': 2_000_000, 'outputTokens': 250_000},
    'c': {'stage': 'adapt', 'provider': 'openai', 'model': 'gpt-5-mini', 'inputTokens': 200_000, 'outputTokens': 100_000},
}


class Gestionnaire:
    def __init__(self, path, headers=None):
        self.path = path
        self.headers = {'Host': '127.0.0.1:53782', **(headers or {})}
        self.rfile = io.BytesIO()
        self.close_connection = False
        self.reponses = []

    def _envoyer(self, status, corps, mime=None):
        self.reponses.append((status, corps))


class Tarifs(unittest.TestCase):
    def test_surcharge_sans_changer_le_code(self):
        grille = discover_costs.tarifs({'pricing': {'gpt-5-mini': {'inputUsdPerMillion': 1, 'outputUsdPerMillion': 1}}})
        self.assertEqual(grille['gpt-5-mini'], {'inputUsdPerMillion': 1.0, 'outputUsdPerMillion': 1.0})
        self.assertEqual(grille['gemini-3.1-flash-lite'], discover_costs.TARIFS_DEFAUT['gemini-3.1-flash-lite'])

    def test_tarifs_invalides_sont_ignorees(self):
        grille = discover_costs.tarifs({'pricing': {'x': {'inputUsdPerMillion': 'gratuit'}, 'y': 3, '*': {'inputUsdPerMillion': 2, 'outputUsdPerMillion': 2}}})
        self.assertNotIn('x', grille)
        self.assertNotIn('y', grille)
        self.assertEqual(grille['*'], {'inputUsdPerMillion': 2.0, 'outputUsdPerMillion': 2.0})

    def test_modele_inconnu_passe_par_le_tarif_prudent(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'prepared-a1'
            folder.mkdir()
            (folder / 'audio-estimate.json').write_text(json.dumps({'provider': 'kokoro'}))
            item = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'source': {'title': 'Mystère'}, 'options': {}}
            discover_costs.Registre(Path(tmp), maintenant=MAINTENANT).enregistrer(
                item, {'k': {'provider': 'gemini', 'model': 'gemini-4-nano', 'inputTokens': 1_000_000, 'outputTokens': 0}}, folder)
            # Étoile : 1 USD l'entrée, 4 USD la sortie par million de jetons.
            self.assertEqual(discover_costs.rapport(tmp, {}, maintenant=MAINTENANT)['months'][0]['geminiUsd'], 1.0)


class RegistreCouts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'abcdefabcdefabcdef01' / 'prepared-a1'
        self.folder.mkdir(parents=True)
        self.item = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'ref': 'a' * 20,
                     'source': {'title': 'Épisode coûté'}, 'options': {'coverage': 'full', 'level': 'B1'}}

    def tearDown(self):
        self.tmp.cleanup()

    def audio(self, **valeurs):
        (self.folder / 'audio-estimate.json').write_text(json.dumps(valeurs))

    def test_une_reprise_ne_compte_pas_deux_fois(self):
        self.audio(provider='deepgram', voice='cora', estimatedUsd=0.09, newCharacters=3000)
        for _ in range(2):
            discover_costs.Registre(self.root, maintenant=MAINTENANT).enregistrer(self.item, APPELS, self.folder)
        data = discover_costs.rapport(self.root, {'tts': {}}, maintenant=MAINTENANT)
        self.assertEqual(len(data['preparations']), 1)
        # Le mois Deepgram vient du registre du budget (coûts réellement engagés) : rien d'engagé ici.
        mois = data['months'][0]
        self.assertEqual((mois['month'], mois['geminiUsd'], mois['openaiUsd'], mois['deepgramUsd']), ('2026-10', 1.875, 0.25, 0.0))
        self.assertAlmostEqual(mois['totalUsd'], 2.125)
        ligne = data['preparations'][0]
        self.assertEqual((ligne['ttsProvider'], ligne['voice'], ligne['deepgramUsd'], ligne['deepgramCharacters']),
                         ('deepgram', 'cora', 0.09, 3000))

    def test_une_regeneration_rajoute_une_ligne(self):
        self.audio(provider='kokoro')
        for revision in (0, 1):
            (self.folder / 'revision.json').write_text(json.dumps({'revision': revision}))
            discover_costs.Registre(self.root, maintenant=MAINTENANT).enregistrer(self.item, APPELS, self.folder)
        data = discover_costs.rapport(self.root, {}, maintenant=MAINTENANT)
        self.assertEqual(len(data['preparations']), 2)
        self.assertAlmostEqual(data['months'][0]['geminiUsd'], 3.75)

    def test_le_mois_precedent_est_rapporte(self):
        self.audio(provider='kokoro')
        discover_costs.Registre(self.root, maintenant=SEPTEMBRE).enregistrer(
            {**self.item, 'id': 'bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb'}, APPELS, self.folder)
        data = discover_costs.rapport(self.root, {}, maintenant=MAINTENANT)
        self.assertEqual([m['month'] for m in data['months']], ['2026-10', '2026-09'])
        self.assertEqual(data['months'][0]['geminiUsd'], 0.0)
        self.assertEqual(data['months'][1]['geminiUsd'], 1.875)

    def test_deepgram_et_ia_sont_additionnes(self):
        self.audio(provider='kokoro')
        discover_costs.Registre(self.root, maintenant=MAINTENANT).enregistrer(self.item, APPELS, self.folder)
        Budget(self.root / '.deepgram', month=lambda: '2026-10').reserve('fragment-1', 100_000, 10)  # 3 USD engagés
        mois = discover_costs.rapport(self.root, {'tts': {}}, maintenant=MAINTENANT)['months'][0]
        self.assertEqual((mois['geminiUsd'], mois['openaiUsd'], mois['deepgramUsd']), (1.875, 0.25, 3.0))
        self.assertAlmostEqual(mois['totalUsd'], 5.125)

    def test_voix_repli_et_jetons_sont_consignes(self):
        self.audio(provider='kokoro', requestedProvider='deepgram', voice='cora', fallbackReason='Clé Deepgram absente.',
                   estimatedUsd=0.5, newCharacters=15000)
        discover_costs.Registre(self.root, maintenant=MAINTENANT).enregistrer(self.item, APPELS, self.folder)
        ligne = discover_costs.rapport(self.root, {}, maintenant=MAINTENANT)['preparations'][0]
        self.assertEqual((ligne['ttsProvider'], ligne['voice'], ligne['deepgramUsd'], ligne['fallbackReason']),
                         ('kokoro', 'cora', 0.0, 'Clé Deepgram absente.'))
        self.assertEqual((ligne['geminiTokens'], ligne['openaiTokens']), (3_750_000, 300_000))
        self.assertEqual(ligne['models'], ['gemini-3.1-flash-lite', 'gpt-5-mini'])

    def test_tarifs_personnalises_changent_le_montant(self):
        self.audio(provider='kokoro')
        config = {'pricing': {'gpt-5-mini': {'inputUsdPerMillion': 1, 'outputUsdPerMillion': 1}}}
        discover_costs.Registre(self.root, maintenant=MAINTENANT).enregistrer(self.item, APPELS, self.folder, config)
        mois = discover_costs.rapport(self.root, config, maintenant=MAINTENANT)['months'][0]
        self.assertEqual((mois['geminiUsd'], mois['openaiUsd']), (1.875, 0.3))

    def test_appels_malformes_sont_ignorees(self):
        self.audio(provider='kokoro')
        discover_costs.Registre(self.root, maintenant=MAINTENANT).enregistrer(
            self.item, {'k': 'bug', 'k2': None, 'k3': {'provider': 'gemini', 'model': 'gemini-3.1-flash-lite'}}, self.folder)
        mois = discover_costs.rapport(self.root, {}, maintenant=MAINTENANT)['months'][0]
        self.assertEqual((mois['geminiUsd'], mois['openaiUsd']), (0.0, 0.0))


class RouteCosts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        folder = self.root / 'abcdefabcdefabcdef01' / 'prepared-a1'
        folder.mkdir(parents=True)
        (folder / 'audio-estimate.json').write_text(json.dumps({'provider': 'deepgram', 'voice': 'vesta', 'estimatedUsd': 0.09, 'newCharacters': 3000}))
        discover_costs.Registre(self.root, maintenant=MAINTENANT).enregistrer(
            {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'source': {'title': 'Épisode'}, 'options': {}}, APPELS, folder)

    def tearDown(self):
        self.tmp.cleanup()

    def test_la_route_donne_les_deux_mois_et_les_preparations(self):
        h = Gestionnaire('/api/discover/costs')
        with mock.patch.object(discover_http.FILE, 'dossier', self.root), \
                mock.patch.object(discover_http.FILE, 'config', {'workerUrl': 'x', 'tts': {}}):
            discover_http.traiter(h, 'GET', '/api/discover/costs')
        self.assertEqual(h.reponses[0][0], 200)
        corps = h.reponses[0][1]
        for cle in ('months', 'budget', 'preparations', 'tarifs', 'pricingConfigured'):
            self.assertIn(cle, corps)
        self.assertEqual(len(corps['months']), 2)
        self.assertEqual(corps['preparations'][0]['title'], 'Épisode')

    def test_aucune_cle_api_ne_sort_jamais(self):
        secrets = {'workerUrl': 'x', 'geminiApiKey': 'CLE-GEMINI-SECRETE-1234', 'openaiApiKey': 'CLE-OPENAI-SECRETE-5678',
                   'deepgramApiKey': 'CLE-DEEPGRAM-SECRETE-9012', 'atelierToken': 'JETON-SECRETE-3456789012345678901234567890'}
        corps = discover_costs.rapport(self.root, secrets, maintenant=MAINTENANT)
        for secret in ('CLE-GEMINI', 'CLE-OPENAI', 'CLE-DEEPGRAM', 'JETON-SECRETE'):
            self.assertNotIn(secret, json.dumps(corps))


class PreparationSimulee(unittest.TestCase):
    """Préparation complète avec client et moteurs factices : le coût apparaît une seule fois dans le mois."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / ('a' * 20)  # dossier de l'épisode ; les registres vivent dans self.base
        self.root.mkdir(parents=True)
        segments = self.root / 'segments.json'
        segments.write_text(json.dumps({'segments': [{'id': 's001', 'text': 'A fact.'}]}))
        self.source = {'segmentsFile': str(segments), 'segmentsSha256': 'hash'}
        self.item = {'id': 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa', 'ref': 'a' * 20, 'leaseToken': 'token',
                     'source': {'title': 'Episode'}, 'options': {'coverage': 'condensed', 'targetMinutes': 12, 'level': 'B1',
                                                                 'style': 'narration', 'faithful': False, 'keepOriginalCopy': False}}
        self.prepared = {'script': {'segments': [{'text': 'A fact.', 'fr': 'Un fait.', 'speaker': 'Narrator', 'sourceSegments': ['s001']}],
                                    'tooShortForSubject': False, 'recommendedMinutes': None, 'keyVocab': []},
                         'evaluation': {'verdict': 'ok'}, 'generation': {}, 'facts': []}
        self.client = mock.Mock()
        self.client.statistiques.return_value = {}
        self.client.appels = dict(APPELS)

    def tearDown(self):
        self.tmp.cleanup()

    def preparer_une_fois(self):
        with mock.patch.object(workflow.adaptation, 'generer', return_value=self.prepared), \
                mock.patch.object(workflow.discover_vocabulary, 'charger', return_value=set()), \
                mock.patch.object(workflow.discover_audio, 'calibrer', return_value={'bf_emma': .7}), \
                mock.patch.object(workflow.discover_audio, 'executer', return_value={'durationMs': 12 * 60_000}), \
                mock.patch.object(workflow.discover_cible, 'requete', side_effect=workflow.discover_cible.ErreurDiscover(404, 'not_found')), \
                mock.patch.object(workflow, 'construire', return_value=({}, {})), \
                mock.patch.object(workflow.discover_cible, 'publier_manifeste', return_value={'status': 'ready'}):
            workflow.preparer(self.item, self.source, self.root, lambda _: None, lambda: None, {}, self.client)

    def test_le_cout_apparait_une_seule_fois(self):
        with mock.patch.object(discover_costs, 'datetime') as dt:  # horloge figée : octobre 2026
            dt.now.return_value = MAINTENANT
            self.preparer_une_fois()
            self.preparer_une_fois()  # reprise : mêmes options, même révision → pas de double comptage
        data = discover_costs.rapport(self.base, {'tts': {}}, maintenant=MAINTENANT)
        self.assertEqual(len(data['preparations']), 1)
        mois = data['months'][0]
        self.assertEqual((mois['geminiUsd'], mois['openaiUsd'], mois['deepgramUsd']), (1.875, 0.25, 0.0))
        ligne = data['preparations'][0]
        self.assertEqual(ligne['title'], 'Episode')
        self.assertEqual(ligne['ttsProvider'], 'kokoro')  # moteur local factice : aucune dépense Deepgram
        self.assertEqual(ligne['voice'], 'cora')

    def test_les_couts_n_interrompent_pas_une_publication_reussie(self):
        with mock.patch.object(workflow.discover_costs, 'enregistrer', side_effect=RuntimeError('registre indisponible')), \
                mock.patch('builtins.print') as silence:
            self.preparer_une_fois()
        silence.assert_called_once()
        publiee = self.root / ('prepared-' + workflow.empreinte(self.item['options'])[:16])
        self.assertTrue((publiee / 'published.json').exists())



class ReponsesEnCache(unittest.TestCase):
    def test_une_reponse_du_cache_n_est_pas_recomptee(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'ep' / 'prepared-x'
            folder.mkdir(parents=True)
            appels = {'a': {'provider': 'gemini', 'model': 'gemini-3.1-flash-lite', 'inputTokens': 1_000_000, 'outputTokens': 0},
                      'b': {'provider': 'gemini', 'model': 'gemini-3.1-flash-lite', 'inputTokens': 1_000_000, 'outputTokens': 0, 'cached': True}}
            discover_costs.Registre(root).enregistrer({'id': 'i1', 'options': {}, 'source': {'title': 'T'}}, appels, folder, {})
            ligne = discover_costs.Registre(root).dernieres(1)[0]
            self.assertEqual(ligne['gemini_in'], 1_000_000)
            self.assertEqual(ligne['gemini_micro'], 250_000)

if __name__ == '__main__':
    unittest.main()
