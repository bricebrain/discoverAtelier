# -*- coding: utf-8 -*-
"""Tests métier du pipeline bilingue (cahier des charges §11).

Lancement :  python3 -m unittest discover -s tests -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bundles   # noqa: E402
import pipeline  # noqa: E402

TEXTE_FR = ("Bonjour à tous. Nous devons comprendre ce qui s'est mal passé. "
            "La décision a été prise sans vote. Les fédérations n'ont pas été "
            "consultées.")
FAUX_MP3 = b"ID3" + b"\x00" * 4096


class BaseBundle(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.patch = mock.patch.object(bundles, "DOSSIER_BUNDLES", self.dossier)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.dossier)

    def creer(self, slug, source, texte):
        meta = bundles.construire_meta(slug, "Titre", f"https://y/{slug}",
                                       source, source, "B1", "culture",
                                       statut="prepared")
        bundles.ecrire_meta(slug, meta)
        self.ecrire(f"{slug}.mp3", FAUX_MP3)
        self.ecrire(f"{slug}.transcript.{source}.txt", texte.encode("utf-8"))
        segments, erreur = pipeline.initialiser_segments(slug)
        self.assertIsNone(erreur)
        return segments

    def ecrire(self, nom, contenu):
        with open(os.path.join(self.dossier, nom), "wb") as f:
            f.write(contenu)

    def lire(self, nom):
        with open(os.path.join(self.dossier, nom), encoding="utf-8") as f:
            return f.read()

    def traduction(self, segments, prefixe="EN"):
        return json.dumps({"segments": [
            {"id": s["id"], "text": f"{prefixe} {s['id']}"} for s in segments]})

    def pedagogie(self, segment_id="s001", **surcharge):
        chunk = {"expression": "figure out", "meaningFr": "comprendre",
                 "exampleEn": "I can't figure it out.", "level": "B1",
                 "type": "phrasal_verb", "sourceSegmentId": segment_id}
        chunk.update(surcharge)
        return json.dumps({"chunks": [chunk], "grammarPoints": []})

    def generer_tts(self, slug):
        """Simule un TTS réussi (comme _executer_tts)."""
        self.ecrire(f"{slug}.audio-en.mp3", FAUX_MP3 + b"en")
        texte = pipeline.texte_complet(pipeline.lire_segments(slug), "en")
        pipeline.enregistrer_tts(slug, pipeline.empreinte(texte), "bf_emma")

    def bundle_fr_complet(self, slug="video-fr"):
        segments = self.creer(slug, "fr", TEXTE_FR)
        _, erreurs = pipeline.enregistrer_traduction(slug, self.traduction(segments))
        self.assertEqual(erreurs, [])
        _, erreurs = pipeline.enregistrer_pedagogie(slug, self.pedagogie())
        self.assertEqual(erreurs, [])
        return segments


class TestSegmentation(unittest.TestCase):
    def test_aucun_mot_perdu(self):
        texte = TEXTE_FR * 5
        segments = pipeline.segmenter(texte)
        self.assertGreater(len(segments), 1)
        self.assertEqual(" ".join(segments).split(), texte.split())

    def test_texte_sans_ponctuation_decoupe(self):
        texte = " ".join(["mot"] * 400)
        segments = pipeline.segmenter(texte)
        self.assertTrue(all(len(s) <= pipeline.SEGMENT_MAX for s in segments))
        self.assertEqual(" ".join(segments).split(), texte.split())


class TestParcoursFrancais(BaseBundle):
    def test_ac02_ac03_ac13_audio_en_distinct_et_selectionne(self):
        self.bundle_fr_complet()
        etat = pipeline.etat_publication("video-fr")
        self.assertFalse(etat["ok"])
        self.assertEqual(etat["statut"], "awaiting_tts")
        self.assertFalse(etat["badges"]["audioEn"],
                         "l'audio FR original ne compte pas comme audio EN")

        self.generer_tts("video-fr")
        etat = pipeline.etat_publication("video-fr")
        self.assertTrue(etat["ok"], etat["raisons"])
        self.assertEqual(etat["publishAudioFile"], "video-fr.audio-en.mp3")
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "video-fr.mp3")),
                        "l'audio original est conservé")

    def test_ac05_bundle_incomplet_raison_visible(self):
        self.creer("video-fr", "fr", TEXTE_FR)
        etat = pipeline.etat_publication("video-fr")
        self.assertFalse(etat["ok"])
        self.assertEqual(etat["statut"], "awaiting_translation")
        self.assertIn("traduction anglaise manquante ou incomplète", etat["raisons"])

    def test_ac09_changer_l_anglais_rend_tts_et_analyse_obsoletes(self):
        segments = self.bundle_fr_complet()
        self.generer_tts("video-fr")
        self.assertTrue(pipeline.etat_publication("video-fr")["ok"])

        modif = json.dumps({"segments": [{"id": segments[0]["id"],
                                          "text": "A corrected sentence."}]})
        _, erreurs = pipeline.enregistrer_traduction("video-fr", modif)
        self.assertEqual(erreurs, [])
        etat = pipeline.etat_publication("video-fr")
        self.assertFalse(etat["ok"])
        self.assertTrue(etat["pedagogieObsolete"])
        self.assertEqual(bundles.lire_meta("video-fr")["englishTextRevision"], 2)

        pipeline.enregistrer_pedagogie("video-fr", self.pedagogie())
        etat = pipeline.etat_publication("video-fr")
        self.assertTrue(etat["audioEnObsolete"])
        self.assertFalse(etat["ok"])

    def test_payload_sans_audio_fr_ni_chemin_local(self):
        self.bundle_fr_complet()
        self.generer_tts("video-fr")
        payload, etat, erreur = pipeline.payload_distant("video-fr")
        self.assertIsNone(erreur)
        self.assertEqual(payload["audioR2Key"], "prepared-content/video-fr-en.mp3")
        self.assertEqual(payload["metadata"]["audioLanguage"], "en")
        self.assertTrue(payload["metadata"]["textFr"].startswith("Bonjour"))
        self.assertTrue(payload["body"].startswith("EN s001"))
        self.assertEqual(len(payload["metadata"]["chunks"]), 1)
        brut = json.dumps(payload)
        self.assertNotIn(self.dossier, brut)
        self.assertNotIn("apiSecret", brut)

    def test_refus_audio_original_pour_source_fr(self):
        nom, erreur = pipeline.fichier_audio_publication(
            "x", {"sourceLanguage": "fr"})
        self.assertEqual(nom, "x.audio-en.mp3")
        self.assertIsNone(erreur)


class TestDuree(unittest.TestCase):
    def test_libelles(self):
        self.assertEqual(pipeline.libelle_duree(42), "42 s")
        self.assertEqual(pipeline.libelle_duree(75), "1 min")
        self.assertEqual(pipeline.libelle_duree(12 * 60 + 20), "12 min")
        self.assertEqual(pipeline.libelle_duree(3900), "1 h 05")

    def test_fichier_illisible(self):
        self.assertIsNone(pipeline.duree_audio_secondes("/inexistant.mp3"))


class TestParcoursAnglais(BaseBundle):
    def test_ac06_audio_original_sans_tts(self):
        segments = self.creer("video-en", "en", "We need to figure it out. "
                                                "It went wrong.")
        etat = pipeline.etat_publication("video-en")
        self.assertIn("traduction française manquante ou incomplète", etat["raisons"])

        pipeline.enregistrer_traduction("video-en", self.traduction(segments, "FR"))
        etat = pipeline.etat_publication("video-en")
        self.assertEqual(etat["statut"], "awaiting_pedagogy")

        pipeline.enregistrer_pedagogie("video-en", self.pedagogie())
        etat = pipeline.etat_publication("video-en")
        self.assertTrue(etat["ok"], etat["raisons"])
        self.assertEqual(etat["publishAudioFile"], "video-en.mp3")
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "video-en.translation.fr.txt")))


class TestValidation(BaseBundle):
    def test_ac07_json_invalide_ne_corrompt_rien(self):
        segments = self.creer("v", "fr", TEXTE_FR)
        pipeline.enregistrer_traduction("v", self.traduction(segments))
        avant = self.lire("v.segments.json")

        for mauvais in ("pas du json", '{"segments": []}',
                        '{"segments": [{"id": "s999", "text": "x"}]}',
                        '{"segments": [{"id": "s001", "text": ""}]}'):
            resume, erreurs = pipeline.enregistrer_traduction("v", mauvais)
            self.assertIsNone(resume)
            self.assertTrue(erreurs)
        self.assertEqual(self.lire("v.segments.json"), avant)

    def test_cloture_markdown_toleree(self):
        segments = self.creer("v", "fr", TEXTE_FR)
        _, erreurs = pipeline.enregistrer_traduction(
            "v", "```json\n" + self.traduction(segments) + "\n```")
        self.assertEqual(erreurs, [])

    def test_ac08_chunk_avec_segment_inexistant_rejete(self):
        self.bundle_fr_complet("v")
        os.remove(os.path.join(self.dossier, "v.pedagogy.json"))
        resume, erreurs = pipeline.enregistrer_pedagogie(
            "v", self.pedagogie(segment_id="s999"))
        self.assertIsNone(resume)
        self.assertTrue(any("s999" in e for e in erreurs))
        self.assertFalse(os.path.exists(os.path.join(self.dossier, "v.pedagogy.json")))

    def test_niveau_et_type_controles(self):
        self.bundle_fr_complet("v")
        os.remove(os.path.join(self.dossier, "v.pedagogy.json"))
        _, erreurs = pipeline.enregistrer_pedagogie(
            "v", self.pedagogie(level="C1", type="slang"))
        self.assertTrue(any("C1" in e for e in erreurs))
        self.assertTrue(any("slang" in e for e in erreurs))

    def test_analyse_sans_chunk_acceptee(self):
        segments = self.creer("v", "fr", TEXTE_FR)
        pipeline.enregistrer_traduction("v", self.traduction(segments))
        _, erreurs = pipeline.enregistrer_pedagogie(
            "v", '{"chunks": [], "grammarPoints": []}')
        self.assertEqual(erreurs, [])
        self.assertTrue(pipeline.etat_publication("v")["badges"]["pedagogie"])

    def test_traduction_par_lots(self):
        texte = " ".join(f"Phrase numéro {i} assez longue pour remplir un segment "
                         f"de traduction cohérent et complet." for i in range(200))
        segments = self.creer("long", "fr", texte)
        self.assertGreater(len(segments), pipeline.TAILLE_LOT_TRADUCTION)
        prompt, info, _ = pipeline.prompt_traduction("long")
        self.assertEqual(info["lot"], 1)
        premier = segments[:pipeline.TAILLE_LOT_TRADUCTION]
        resume, _ = pipeline.enregistrer_traduction("long", self.traduction(premier))
        self.assertFalse(resume["complete"])
        _, info, _ = pipeline.prompt_traduction("long")
        self.assertEqual(info["lot"], 2)
        self.assertIn(segments[pipeline.TAILLE_LOT_TRADUCTION]["id"],
                      pipeline.prompt_traduction("long")[0])


class TestCompatibilite(BaseBundle):
    def test_ac12_ancien_bundle_migration_guidee(self):
        meta = {"id": "ancien", "title": "Ancien", "audioLanguage": "fr",
                "status": "imported"}
        bundles.ecrire_meta("ancien", meta)
        self.ecrire("ancien.mp3", FAUX_MP3)
        self.ecrire("ancien.transcript.fr.txt", TEXTE_FR.encode())
        self.ecrire("ancien.translation.en.txt", b"Old English text.")
        etat = pipeline.etat_publication("ancien")
        self.assertFalse(etat["ok"])
        self.assertTrue(etat["ancienFormat"])
        self.assertTrue(any("ancien format" in r for r in etat["raisons"]))
        # Le prompt crée les segments sans toucher aux anciens fichiers
        prompt, _, erreur = pipeline.prompt_traduction("ancien")
        self.assertIsNone(erreur)
        self.assertIn("s001", prompt)
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "ancien.translation.en.txt")))


class TestPublication(BaseBundle):
    def setUp(self):
        super().setUp()
        self.patch_config = mock.patch.object(
            bundles, "charger_config_import",
            return_value=({"workerUrl": "https://w", "apiSecret": "s",
                           "profileId": "default"}, None))
        self.patch_config.start()

    def tearDown(self):
        self.patch_config.stop()
        super().tearDown()

    def test_bundle_incomplet_jamais_envoye(self):
        self.creer("v", "fr", TEXTE_FR)
        with mock.patch.object(bundles, "_requete_worker") as requete:
            ok, message = pipeline.publier("v")
        self.assertFalse(ok)
        requete.assert_not_called()

    def test_ac10_echec_reseau_puis_retry(self):
        self.bundle_fr_complet("v")
        self.generer_tts("v")
        with mock.patch.object(bundles, "_requete_worker",
                               side_effect=RuntimeError("worker injoignable")):
            ok, _ = pipeline.publier("v")
        self.assertFalse(ok)
        etat = pipeline.etat_publication("v")
        self.assertEqual(etat["statut"], "publish_failed")
        self.assertTrue(etat["ok"], "le retry reste possible")
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "v.audio-en.mp3")))

        with mock.patch.object(bundles, "_requete_worker", return_value="{}") as requete:
            ok, _ = pipeline.publier("v")
        self.assertTrue(ok)
        appels = [c.args[0] for c in requete.call_args_list]
        self.assertIn("https://w/content", appels)
        self.assertTrue(any("v-en.mp3" in a for a in appels))
        envoye = requete.call_args_list[0].kwargs["donnees"]
        self.assertTrue(envoye.endswith(b"en"), "c'est l'audio EN qui est envoyé")
        self.assertEqual(pipeline.etat_publication("v")["statut"], "published")

    def test_ac14_modifier_le_francais_seul(self):
        segments = self.bundle_fr_complet("v")
        self.generer_tts("v")
        with mock.patch.object(bundles, "_requete_worker", return_value="{}"):
            pipeline.publier("v")
        # Correction du texte FR source (segments.json édité)
        segments = pipeline.lire_segments("v")
        segments[0]["fr"] = "Bonjour à toutes et à tous."
        pipeline.ecrire_segments("v", segments)
        etat = pipeline.etat_publication("v")
        self.assertFalse(etat["audioEnObsolete"], "pas de TTS inutile")
        self.assertTrue(etat["ok"])
        self.assertEqual(etat["statut"], "ready_to_publish",
                         "republication du contenu textuel proposée")


if __name__ == "__main__":
    unittest.main()
