# -*- coding: utf-8 -*-
"""LOT 1 — horodatage (SRT MacWhisper, Kokoro segment par segment),
contrôles des timings, débit, versions et clés R2 immuables.
Critères : EA-01, EA-02 (calcul), EA-03, v1.2 § 6.1 / § 6.4 / § 6.5."""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bundles      # noqa: E402
import horodatage   # noqa: E402
import pipeline     # noqa: E402
import transcription  # noqa: E402
import tts_kokoro   # noqa: E402
from test_pipeline import FAUX_MP3, TEXTE_FR, BaseBundle  # noqa: E402

SRT = """﻿1
00:00:00,000 --> 00:00:02,500
Hello everyone, and welcome back.

2
00:00:02,600 --> 00:00:05,000
Today we need to figure out
what went wrong.

3
00:00:05,100 --> 00:00:09,900
The decision was taken without a vote, and the federations were not consulted at all.

"""


class TestSrt(unittest.TestCase):
    def test_lecture(self):
        repliques = horodatage.lire_srt(SRT.replace("\n", "\r\n"))
        self.assertEqual(len(repliques), 3)
        self.assertEqual(repliques[0], {"startMs": 0, "endMs": 2500,
                                        "text": "Hello everyone, and welcome back."})
        self.assertEqual(repliques[1]["text"], "Today we need to figure out what went wrong.")
        self.assertEqual(repliques[2]["endMs"], 9900)

    def test_virgule_ou_point_et_heures(self):
        repliques = horodatage.lire_srt("1\n01:02:03.5 --> 01:02:04.25\nHi.\n")
        self.assertEqual(repliques[0]["startMs"], 3723500)
        self.assertEqual(repliques[0]["endMs"], 3724250)

    def test_blocs_vides_ignores(self):
        self.assertEqual(horodatage.lire_srt("1\n00:00:01,000 --> 00:00:02,000\n\n\n"), [])
        self.assertEqual(horodatage.lire_srt(""), [])

    def test_texte_derive(self):
        self.assertEqual(horodatage.srt_vers_texte(horodatage.lire_srt(SRT)).splitlines()[1],
                         "Today we need to figure out what went wrong.")


class TestRegroupement(unittest.TestCase):
    def test_ne_coupe_jamais_une_replique_et_garde_l_ordre(self):
        repliques = [{"startMs": i * 1000, "endMs": i * 1000 + 900, "text": f"Phrase numero {i} ici."}
                     for i in range(30)]
        segments = horodatage.regrouper_repliques(repliques, cible=60)
        textes = " ".join(s["text"] for s in segments)
        self.assertEqual(textes, " ".join(r["text"] for r in repliques))
        for s in segments:
            self.assertLessEqual(len(s["text"]), 60)
        self.assertEqual(segments[0]["startMs"], 0)
        self.assertEqual(segments[-1]["endMs"], 29900)
        for a, b in zip(segments, segments[1:]):
            self.assertLess(a["endMs"], b["startMs"])

    def test_replique_plus_longue_que_la_cible(self):
        segments = horodatage.regrouper_repliques(horodatage.lire_srt(SRT), cible=40)
        self.assertEqual([s["startMs"] for s in segments], [0, 2600, 5100])

    def test_cible_par_defaut(self):
        segments = horodatage.regrouper_repliques(horodatage.lire_srt(SRT))
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0]["startMs"], segments[0]["endMs"]), (0, 9900))


class TestControles(unittest.TestCase):
    def seg(self, *bornes):
        return [{"id": f"s{i:03d}", "startMs": a, "endMs": b} for i, (a, b) in enumerate(bornes, 1)]

    def test_valides(self):
        self.assertEqual(horodatage.verifier_timings(self.seg((0, 1000), (1100, 2000)), 2400), ("valid", []))

    def test_chevauchement_tolere_jusqu_a_200_ms(self):
        self.assertEqual(horodatage.verifier_timings(self.seg((0, 1200), (1000, 2000)))[0], "valid")
        statut, raisons = horodatage.verifier_timings(self.seg((0, 1300), (1000, 2000)))
        self.assertEqual(statut, "invalid")
        self.assertIn("chevauche", raisons[0])

    def test_non_croissants(self):
        self.assertEqual(horodatage.verifier_timings(self.seg((5000, 6000), (1000, 2000)))[0], "invalid")
        self.assertEqual(horodatage.verifier_timings(self.seg((2000, 1000)))[0], "invalid")

    def test_fin_apres_la_duree(self):
        self.assertEqual(horodatage.verifier_timings(self.seg((0, 2500)), 2000)[0], "valid")
        self.assertEqual(horodatage.verifier_timings(self.seg((0, 2501)), 2000)[0], "invalid")

    def test_absents_ou_partiels(self):
        self.assertEqual(horodatage.verifier_timings(self.seg((None, None))), ("absent", []))
        self.assertEqual(horodatage.verifier_timings(self.seg((0, 1000), (None, None)))[0], "invalid")


class TestDebit(unittest.TestCase):
    def test_par_segment(self):
        self.assertEqual(horodatage.mots_par_minute("one two three four", 0, 1500), 160)
        self.assertEqual(horodatage.mots_par_minute("I should've told you", 0, 1500), 160)
        self.assertIsNone(horodatage.mots_par_minute("one", 0, 100))
        self.assertIsNone(horodatage.mots_par_minute("one", None, 1000))

    def test_global_hors_silences(self):
        segments = [{"en": "one two three", "startMs": 0, "endMs": 1000},
                    {"en": "four five six", "startMs": 5000, "endMs": 6000}]
        self.assertEqual(horodatage.debit_global(segments), 180)


# Extrait réel (raccourci) d'une piste YouTube automatique : écho de la ligne précédente et cues de 10 ms.
VTT_AUTOMATIQUE = """WEBVTT
Kind: captions
Language: en

00:00:00.500 --> 00:00:03.000 align:start position:0%
 
[music]

00:00:03.000 --> 00:00:04.950 align:start position:0%
 
&gt;&gt; For<00:00:03.200><c> me,</c><00:00:03.400><c> it's</c><00:00:03.600><c> great.</c><00:00:04.000><c> We</c><00:00:04.400><c> play</c>

00:00:04.950 --> 00:00:04.960 align:start position:0%
&gt;&gt; For me, it's great. We play
 

00:00:04.960 --> 00:00:06.000 align:start position:0%
&gt;&gt; For me, it's great. We play
well<00:00:05.200><c> together.</c><00:00:05.600><c> &gt;&gt;</c><00:00:05.800><c> Merci.</c>

00:00:06.000 --> 00:00:06.010 align:start position:0%
well together. &gt;&gt; Merci.
 
"""


class TestVttAutomatique(unittest.TestCase):
    def test_phrases_sans_echo_ni_annotations(self):
        phrases = horodatage.lire_vtt_automatique(VTT_AUTOMATIQUE)
        self.assertEqual([p["text"] for p in phrases],
                         ["For me, it's great.", "We play well together.", "Merci."])
        self.assertEqual([p["startMs"] for p in phrases], [3000, 4000, 5800])

    def test_une_phrase_finit_avec_son_dernier_mot(self):
        phrases = horodatage.lire_vtt_automatique(VTT_AUTOMATIQUE)
        # « great. » est dans la cue qui finit à 4 950 ms, mais la phrase suivante commence à 4 000 ms.
        self.assertEqual([p["endMs"] for p in phrases], [4000, 5800, 6000])
        statut, _ = horodatage.verifier_timings(horodatage.regrouper_repliques(phrases))
        self.assertEqual(statut, "valid")

    def test_phrase_sans_ponctuation_coupee(self):
        mots = "".join(f"<00:00:{10 + i // 10:02d}.{(i % 10) * 100:03d}><c> mot</c>" for i in range(120))
        vtt = "WEBVTT\n\n00:00:09.000 --> 00:00:23.000\n \ndebut" + mots + "\n"
        phrases = horodatage.lire_vtt_automatique(vtt)
        self.assertGreater(len(phrases), 1)
        self.assertTrue(all(len(p["text"]) <= horodatage.PHRASE_MAX for p in phrases))

    def test_vide(self):
        self.assertEqual(horodatage.lire_vtt_automatique("WEBVTT\n"), [])


class TestTimingsKokoro(unittest.TestCase):
    def test_calcul_sur_les_echantillons(self):
        timings, total = tts_kokoro.calculer_timings(
            [("s001", [24000]), ("s002", [12000, 12000])],
            taux=24000, silence_bloc=0.5, silence_segment=1.0)
        self.assertEqual(timings, [
            {"id": "s001", "startMs": 0, "endMs": 1000},
            # 1 s de parole + 1 s de silence, puis 0,5 s + 0,5 s silence + 0,5 s
            {"id": "s002", "startMs": 2000, "endMs": 3500},
        ])
        self.assertEqual(total, 24000 * 4.5)

    def test_valeurs_par_defaut_coherentes(self):
        timings, _ = tts_kokoro.calculer_timings([("s001", [2400]), ("s002", [2400])])
        self.assertEqual(timings[1]["startMs"], 100 + round(tts_kokoro.SILENCE_ENTRE_SEGMENTS * 1000))
        statut, _ = horodatage.verifier_timings(timings)
        self.assertEqual(statut, "valid")


class TestVersions(unittest.TestCase):
    def test_revision_source(self):
        self.assertEqual(len(pipeline.revision_source("Hello")), 16)
        self.assertEqual(pipeline.revision_source("Hello\r\n"), pipeline.revision_source("Hello"))
        self.assertNotEqual(pipeline.revision_source(b"a"), pipeline.revision_source(b"b"))

    def test_cle_et_variante(self):
        self.assertEqual(pipeline.cle_audio_r2("cyber", "1a2b3c4d"),
                         "prepared-content/cyber-faithful-1a2b3c4d.mp3")
        self.assertEqual(pipeline.id_variante("cyber"), "cyber~faithful")


class BaseHorodatage(BaseBundle):
    def bundle_en_srt(self, slug="e"):
        meta = bundles.construire_meta(slug, "Titre", f"https://y/{slug}", "en", "en",
                                       "B1", "culture", statut="prepared")
        bundles.ecrire_meta(slug, meta)
        self.ecrire(f"{slug}.mp3", FAUX_MP3)
        self.ecrire(f"{slug}.transcript.en.srt", SRT.encode("utf-8"))
        self.ecrire(f"{slug}.transcript.en.txt",
                    horodatage.srt_vers_texte(horodatage.lire_srt(SRT)).encode("utf-8"))
        segments, erreur = pipeline.initialiser_segments(slug)
        self.assertIsNone(erreur)
        return segments

    def completer(self, slug, segments, prefixe="FR"):
        pipeline.enregistrer_traduction(slug, self.traduction(segments, prefixe))
        pipeline.enregistrer_pedagogie(slug, self.pedagogie())


class TestSourceAnglaise(BaseHorodatage):
    def test_ea01_segments_horodates_depuis_le_srt(self):
        segments = self.bundle_en_srt()
        self.assertEqual(segments[0]["startMs"], 0)
        self.assertEqual(segments[-1]["endMs"], 9900)
        infos = pipeline.lire_infos_segments("e")
        self.assertEqual(infos, {"segmentationVersion": 1, "timingSource": "macwhisper_srt"})

    def test_la_traduction_conserve_timings_et_version(self):
        segments = self.bundle_en_srt()
        self.completer("e", segments)
        relu = pipeline.lire_segments("e")
        self.assertEqual(relu[0]["startMs"], 0)
        self.assertEqual(pipeline.lire_infos_segments("e")["timingSource"], "macwhisper_srt")

    def test_payload_publie_les_timings_et_les_versions(self):
        segments = self.bundle_en_srt()
        self.completer("e", segments)
        with mock.patch.object(pipeline, "duree_audio_secondes", return_value=10.0):
            payload, etat, erreur = pipeline.payload_distant("e")
        self.assertIsNone(erreur)
        m = payload["metadata"]
        self.assertEqual(m["timingSource"], "macwhisper_srt")
        self.assertEqual(m["timingStatus"], "valid")
        self.assertEqual(m["segmentationVersion"], 1)
        self.assertEqual(m["variantId"], "e~faithful")
        self.assertRegex(m["audioRevision"], r"^[0-9a-f]{8}$")
        self.assertEqual(payload["audioR2Key"], f"prepared-content/e-faithful-{m['audioRevision']}.mp3")
        self.assertEqual(m["sourceRevision"], pipeline.revision_source(FAUX_MP3))
        self.assertEqual(m["segments"][0]["startMs"], 0)
        self.assertIsInstance(m["segments"][0]["wordsPerMinute"], int)
        self.assertIsInstance(m["wordsPerMinute"], int)
        self.assertEqual(m["contentRevision"], etat["revision"])

    def test_timings_invalides_publies_sans_timings(self):
        segments = self.bundle_en_srt()
        self.completer("e", segments)
        with mock.patch.object(pipeline, "duree_audio_secondes", return_value=5.0):
            payload, _, erreur = pipeline.payload_distant("e")
        self.assertIsNone(erreur)  # publiable quand même
        m = payload["metadata"]
        self.assertEqual(m["timingStatus"], "invalid")
        self.assertTrue(all(s["startMs"] is None for s in m["segments"]))

    def test_nouvel_audio_nouvelle_cle_et_nouvelle_revision(self):
        segments = self.bundle_en_srt()
        self.completer("e", segments)
        payload1, etat1, _ = pipeline.payload_distant("e")
        self.ecrire("e.mp3", FAUX_MP3 + b"v2")
        payload2, etat2, _ = pipeline.payload_distant("e")
        self.assertNotEqual(payload1["audioR2Key"], payload2["audioR2Key"])
        self.assertNotEqual(etat1["revision"], etat2["revision"])

    def test_publication_envoie_contentId_et_memorise_la_cle(self):
        segments = self.bundle_en_srt()
        self.completer("e", segments)
        appels = []
        with mock.patch.object(bundles, "charger_config_import",
                               return_value=({"workerUrl": "https://w", "apiSecret": "s",
                                              "profileId": "default"}, None)), \
             mock.patch.object(bundles, "_requete_worker",
                               side_effect=lambda url, **_: appels.append(url) or "{}"):
            ok, _ = pipeline.publier("e")
        self.assertTrue(ok)
        self.assertIn("&contentId=e", appels[0])
        publication = bundles.lire_meta("e")["publication"]
        self.assertRegex(publication["audioR2Key"], r"^prepared-content/e-faithful-[0-9a-f]{8}\.mp3$")


class TestHorodaterAncienBundle(BaseHorodatage):
    def test_avertit_puis_resegmente_avec_sauvegarde(self):
        segments = self.creer("old", "en", "We need to figure it out. It went wrong.")
        self.completer("old", segments)
        possible, avertissement = pipeline.horodatage_possible("old")
        self.assertTrue(possible)
        self.assertIn("traduction", avertissement)
        self.ecrire("old.transcript.en.srt", SRT.encode("utf-8"))
        nouveaux, erreur = pipeline.horodater("old")
        self.assertIsNone(erreur)
        self.assertEqual(nouveaux[0]["startMs"], 0)
        self.assertIsNone(nouveaux[0]["fr"])
        self.assertEqual(pipeline.lire_infos_segments("old"),
                         {"segmentationVersion": 2, "timingSource": "macwhisper_srt"})
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "old.segments.v1.bak.json")))
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "old.pedagogy.v1.bak.json")))
        self.assertFalse(os.path.exists(os.path.join(self.dossier, "old.pedagogy.json")))
        self.assertFalse(pipeline.etat_publication("old")["ok"])
        self.assertEqual(pipeline.horodatage_possible("old"), (False, "déjà horodaté"))

    def test_sans_srt_ou_source_fr(self):
        self.creer("old", "en", "Hello there.")
        self.assertEqual(pipeline.horodater("old")[0], None)
        self.creer("fr", "fr", TEXTE_FR)
        self.assertFalse(pipeline.horodatage_possible("fr")[0])


class TestSourceFrancaiseKokoro(BaseHorodatage):
    def timings(self, slug, segments, texte_hash=None):
        pipeline.ecrire_json(os.path.join(self.dossier, f"{slug}.audio-en.timings.json"), {
            "textHash": texte_hash or pipeline.empreinte(pipeline.texte_complet(segments, "en")),
            "voice": "bf_emma", "segmentationVersion": 1,
            "timings": [{"id": s["id"], "startMs": i * 2000, "endMs": i * 2000 + 1500}
                        for i, s in enumerate(segments)]})

    def test_les_timings_fr_ne_sont_jamais_reutilises(self):
        segments = self.creer("v", "fr", TEXTE_FR)
        self.assertIsNone(segments[0]["startMs"])
        self.assertIsNone(pipeline.lire_infos_segments("v")["timingSource"])

    def test_timings_kokoro_publies(self):
        self.bundle_fr_complet("v")
        self.generer_tts("v")
        segments = pipeline.lire_segments("v")
        self.timings("v", segments)
        payload, etat, erreur = pipeline.payload_distant("v")
        self.assertIsNone(erreur)
        m = payload["metadata"]
        self.assertEqual((m["timingSource"], m["timingStatus"]), ("kokoro", "valid"))
        self.assertEqual((m["segments"][0]["startMs"], m["segments"][0]["endMs"]), (0, 1500))
        self.assertEqual(m["audioOrigin"], "kokoro_tts")
        self.assertEqual(etat["horodatage"]["timingStatus"], "valid")

    def test_ea03_texte_anglais_modifie_timings_obsoletes(self):
        self.bundle_fr_complet("v")
        self.generer_tts("v")
        segments = pipeline.lire_segments("v")
        self.timings("v", segments)
        modif = json.dumps({"segments": [{"id": segments[0]["id"], "text": "A corrected sentence."}]})
        pipeline.enregistrer_traduction("v", modif)
        self.assertIsNone(pipeline.lire_timings_kokoro("v", pipeline.lire_segments("v")))
        etat = pipeline.etat_publication("v")
        self.assertTrue(etat["audioEnObsolete"])

    def test_sans_fichier_de_timings_pas_d_horodatage(self):
        self.bundle_fr_complet("v")
        self.generer_tts("v")
        payload, _, _ = pipeline.payload_distant("v")
        self.assertEqual(payload["metadata"]["timingStatus"], "absent")
        self.assertIsNone(payload["metadata"]["segments"][0]["startMs"])


class TestMacWhisperSrt(BaseBundle):
    def test_ecrit_le_srt_et_en_derive_le_txt(self):
        base = os.path.join(self.dossier, "x.transcript.en")

        def faux_mw(commande, **_options):
            self.assertIn("srt", commande)
            with open(commande[commande.index("--output") + 1], "w", encoding="utf-8") as f:
                f.write(SRT)
            return mock.Mock(returncode=0, stderr="", stdout="")

        with mock.patch.object(transcription, "trouver_macwhisper", return_value="mw"), \
             mock.patch.object(transcription.subprocess, "run", faux_mw):
            chemin_txt, source = transcription.transcrire_macwhisper("x.mp3", base, "en")
        self.assertEqual(chemin_txt, base + ".txt")
        self.assertIn("SRT", source)
        self.assertTrue(os.path.exists(base + ".srt"))
        self.assertEqual(self.lire("x.transcript.en.txt").splitlines()[0], "Hello everyone, and welcome back.")
        self.assertEqual(bundles.decrire_fichiers("x")["transcriptSrt"], "x.transcript.en.srt")


if __name__ == "__main__":
    unittest.main()
