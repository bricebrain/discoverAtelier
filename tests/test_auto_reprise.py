# -*- coding: utf-8 -*-
"""Auto-publication (AC-04, AC-05) et reprise après redémarrage (AC-15).

Lancement :  python3 -m unittest discover -s tests -v
"""

import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bundles             # noqa: E402
import convertisseur_web   # noqa: E402
import pipeline            # noqa: E402
from test_pipeline import FAUX_MP3, TEXTE_FR, BaseBundle  # noqa: E402


class FauxKokoro:
    """Remplace le processus venv-tts : écrit le .wav demandé et, en mode
    segments, les timings (1 s par segment, comme tts_kokoro.py)."""

    def __init__(self, commande, **_options):
        with open(commande[commande.index("--sortie") + 1], "wb") as f:
            f.write(b"RIFF")
        if "--segments" in commande:
            with open(commande[commande.index("--segments") + 1], encoding="utf-8") as f:
                segments = json.load(f)
            with open(commande[commande.index("--timings") + 1], "w", encoding="utf-8") as f:
                json.dump([{"id": s["id"], "startMs": i * 1350, "endMs": i * 1350 + 1000}
                           for i, s in enumerate(segments)], f)
        self.stdout = iter(["PROGRESSION 1/1\n", "OK 2s sortie.wav\n"])

    def wait(self):
        return 0


def faux_ffmpeg(commande, **_options):
    with open(commande[-1], "wb") as f:
        f.write(FAUX_MP3 + b"en")
    return mock.Mock(returncode=0)


class BaseServeur(BaseBundle):
    def setUp(self):
        super().setUp()
        convertisseur_web.IMPORTS.clear()
        convertisseur_web.TTS_ETATS.clear()
        self.reseau = mock.patch.object(bundles, "_requete_worker",
                                        return_value="{}")
        self.requete = self.reseau.start()
        self.config = mock.patch.object(
            bundles, "charger_config_import",
            return_value=({"workerUrl": "https://w", "apiSecret": "s",
                           "profileId": "default"}, None))
        self.config.start()

    def tearDown(self):
        self.reseau.stop()
        self.config.stop()
        super().tearDown()

    def activer_auto(self, slug, actif=True):
        meta = bundles.lire_meta(slug)
        meta["autoPublish"] = actif
        bundles.ecrire_meta(slug, meta)

    def attendre_import(self, slug):
        for _ in range(100):
            etat = convertisseur_web.instantane_imports().get(slug)
            if etat and etat["statut"] != "en cours":
                return etat
            time.sleep(0.02)
        self.fail("import non terminé")

    def executer_tts(self, slug):
        """Fait tourner le vrai _executer_tts avec Kokoro/ffmpeg simulés."""
        with mock.patch.object(convertisseur_web, "CHEMIN_PYTHON_TTS", sys.executable), \
             mock.patch.object(convertisseur_web, "trouver_ffmpeg", return_value="ffmpeg"), \
             mock.patch.object(convertisseur_web.subprocess, "Popen", FauxKokoro), \
             mock.patch.object(convertisseur_web.subprocess, "run", faux_ffmpeg):
            convertisseur_web._executer_tts(slug, "bf_emma")


class TestAutoPublication(BaseServeur):
    def test_ac04_publication_automatique_apres_tts(self):
        self.bundle_fr_complet("v")
        self.activer_auto("v")
        self.executer_tts("v")

        self.assertEqual(convertisseur_web.instantane_tts()["v"]["statut"], "ok")
        self.assertEqual(self.attendre_import("v")["statut"], "ok")
        self.assertEqual(pipeline.etat_publication("v")["statut"], "published")
        audio_envoye = self.requete.call_args_list[0].kwargs["donnees"]
        self.assertTrue(audio_envoye.endswith(b"en"), "audio Kokoro envoyé")
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "v.mp3")))
        self.assertFalse(any(n.endswith((".wav", ".tmp.mp3", ".tts-input.en.txt", ".tts-input.en.json", ".tts-timings.json"))
                             for n in os.listdir(self.dossier)))

    def test_ac04_dernier_prerequis_valide_apres_le_tts(self):
        segments = self.creer("v", "fr", TEXTE_FR)
        self.activer_auto("v")
        pipeline.enregistrer_traduction("v", self.traduction(segments))
        self.executer_tts("v")
        self.assertNotIn("v", convertisseur_web.instantane_imports(),
                         "analyse pédagogique pas encore validée")

        pipeline.enregistrer_pedagogie("v", self.pedagogie())
        self.assertTrue(convertisseur_web.apres_modification("v"))
        self.assertEqual(self.attendre_import("v")["statut"], "ok")

    def test_ac05_bundle_incomplet_pas_d_import(self):
        segments = self.creer("v", "fr", TEXTE_FR)
        self.activer_auto("v")
        pipeline.enregistrer_traduction("v", self.traduction(segments))
        pipeline.enregistrer_pedagogie("v", self.pedagogie())
        self.assertFalse(convertisseur_web.apres_modification("v"))
        ok, raison = pipeline.doit_auto_publier("v")
        self.assertIn("audio anglais à générer", raison)
        self.requete.assert_not_called()

    def test_option_desactivee(self):
        self.bundle_fr_complet("v")
        self.executer_tts("v")
        self.assertNotIn("v", convertisseur_web.instantane_imports())
        self.requete.assert_not_called()
        self.assertEqual(pipeline.etat_publication("v")["statut"], "ready_to_publish")

    def test_source_en_sans_tts(self):
        segments = self.creer("e", "en", "We need to figure it out.")
        self.activer_auto("e")
        pipeline.enregistrer_traduction("e", self.traduction(segments, "FR"))
        pipeline.enregistrer_pedagogie("e", self.pedagogie())
        self.assertTrue(convertisseur_web.apres_modification("e"))
        self.assertEqual(self.attendre_import("e")["statut"], "ok")

    def test_pas_de_republication_ni_de_retry_automatique(self):
        self.bundle_fr_complet("v")
        self.activer_auto("v")
        self.executer_tts("v")
        self.attendre_import("v")
        self.assertFalse(convertisseur_web.apres_modification("v"),
                         "version déjà publiée")

        # On efface la trace de publication et on simule une panne réseau
        self.requete.side_effect = RuntimeError("worker injoignable")
        meta = bundles.lire_meta("v")
        meta["publication"] = {}
        bundles.ecrire_meta("v", meta)
        convertisseur_web.IMPORTS.clear()
        self.assertTrue(convertisseur_web.apres_modification("v"))
        self.assertEqual(self.attendre_import("v")["statut"], "echec")
        convertisseur_web.IMPORTS.clear()
        self.assertFalse(convertisseur_web.apres_modification("v"),
                         "un échec n'est pas relancé automatiquement")


class TestReprise(BaseServeur):
    def test_ac15_jobs_recharges_et_interrompus(self):
        jobs = {"jobs": [
            {"id": "job-7", "url": "https://y/a", "statut": "transcribing",
             "slug": "a", "langue": "fr", "autoPublish": True},
            {"id": "job-3", "url": "https://y/b", "statut": "awaiting_translation",
             "slug": "b", "langue": "en"}]}
        with open(os.path.join(self.dossier, "_jobs.json"), "w") as f:
            json.dump(jobs, f)
        file_jobs = convertisseur_web.FileJobs()
        file_jobs.charger()
        etats = {j["id"]: j for j in file_jobs.instantane()}
        self.assertEqual(etats["job-7"]["statut"], "failed")
        self.assertIn("Relancer", etats["job-7"]["message"])
        self.assertTrue(etats["job-7"]["autoPublish"])
        self.assertEqual(etats["job-3"]["statut"], "awaiting_translation")
        self.assertEqual(file_jobs._compteur, 7)
        self.assertNotIn("_jobs", bundles.lister_slugs())

    def test_ac15_publication_interrompue(self):
        self.bundle_fr_complet("v")
        self.executer_tts("v")
        meta = bundles.lire_meta("v")
        meta["publication"] = {"status": "publishing"}
        bundles.ecrire_meta("v", meta)

        actions = pipeline.reprendre_apres_redemarrage("v")
        self.assertIn("publication interrompue", actions)
        etat = pipeline.etat_publication("v")
        self.assertEqual(etat["statut"], "publish_failed")
        self.assertTrue(etat["ok"], "Réessayer reste possible")
        self.assertIn("redémarrage", etat["publication"]["lastError"])

    def test_ac15_tts_interrompu(self):
        segments = self.creer("v", "fr", TEXTE_FR)
        pipeline.enregistrer_traduction("v", self.traduction(segments))
        pipeline.marquer_tts("v", "generating")
        self.ecrire("v.tts.wav", b"RIFF")
        self.ecrire("v.audio-en.tmp.mp3", b"ID3")

        actions = pipeline.reprendre_apres_redemarrage("v")
        self.assertIn("TTS interrompu", actions)
        self.assertFalse(any(n.endswith((".wav", ".tmp.mp3"))
                             for n in os.listdir(self.dossier)))
        etat = pipeline.etat_publication("v")
        self.assertTrue(any("interrompue" in r for r in etat["raisons"]))
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "v.mp3")))


if __name__ == "__main__":
    unittest.main()
