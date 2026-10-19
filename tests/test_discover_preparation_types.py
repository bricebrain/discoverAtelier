"""Quiz et coûts : parcours partagé pour chacun des cinq types de préparation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from discover_simulation import QUESTIONS, Simulation


class QuizTousTypes(unittest.TestCase):
    def simuler(self, kind, quiz='valid'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        simulation = Simulation(Path(tmp.name), kind, quiz).executer()
        self.assertTrue(simulation.worker.ready, simulation.consumer.message)
        self.assertIsNone(simulation.consumer.item)
        self.assertFalse(any(path.endswith(('/fail', '/release')) for _, path, _ in simulation.worker.events))
        return simulation

    def test_trois_questions_publiees_et_cout_par_type(self):
        for kind in ('episode', 'youtube', 'reflection', 'article', 'dossier'):
            with self.subTest(kind=kind):
                sim = self.simuler(kind)
                manifest = sim.worker.manifest
                expected = {'episode': 'podcast', 'article': 'reflection'}.get(kind, kind)
                self.assertEqual(manifest['content']['sourceType'], expected)
                variant = next(v for v in manifest['variants'] if v['kind'] == 'adaptation')
                self.assertEqual(variant['quiz'], QUESTIONS)
                self.assertTrue(all('quiz' not in v for v in manifest['variants'] if v['kind'] != 'adaptation'))
                segments = json.loads(sim.worker.uploads[variant['segmentsFile']])['segments']
                for question in variant['quiz']:
                    self.assertLess(question['segmentIndex'], len(segments))
                quiz_prompt = next(p for p in sim.ai.prompts if p.startswith('Create exactly three'))
                self.assertIn('CEFR level B1', quiz_prompt)
                for segment in segments:
                    self.assertIn(segment['text'], quiz_prompt)
                row = sim.costs['preparations'][0]
                self.assertEqual(row['quizUsd'], .003)
                self.assertGreater(row['geminiUsd'], row['quizUsd'])
                self.assertEqual(row['geminiUsd'], variant['generation']['calls'] * .003)
                self.assertEqual(row['totalUsd'], row['geminiUsd'])

    def test_quiz_invalide_ou_ia_indisponible_ne_bloque_aucun_type(self):
        for kind in ('episode', 'youtube', 'reflection', 'article', 'dossier'):
            for quiz in ('invalid', 'unavailable'):
                with self.subTest(kind=kind, quiz=quiz), mock.patch('builtins.print'):
                    sim = self.simuler(kind, quiz)
                    self.assertTrue(all('quiz' not in v for v in sim.worker.manifest['variants']))
                    # Les trois tentatives invalides sont facturées ; la panne sans réponse n'a pas de jetons.
                    self.assertEqual(sim.costs['preparations'][0]['quizUsd'], .009 if quiz == 'invalid' else 0)

    def test_desactivation_ne_genere_aucune_question_pour_aucun_type(self):
        for kind in ('episode', 'youtube', 'reflection', 'article', 'dossier'):
            with self.subTest(kind=kind):
                sim = self.simuler(kind, 'disabled')
                self.assertFalse(any(p.startswith('Create exactly three') for p in sim.ai.prompts))
                self.assertTrue(all('quiz' not in v for v in sim.worker.manifest['variants']))
                self.assertEqual(sim.costs['preparations'][0]['quizUsd'], 0)
