#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Génération d'audio anglais avec Kokoro TTS (modèle local).

Exécuté par convertisseur_web.py via l'environnement dédié
`venv-tts` (Python 3.12 — kokoro-onnx exige un onnxruntime récent).

Usage :
    venv-tts/bin/python tts_kokoro.py \
        --voix bf_emma --sortie sortie.wav texte.txt
    venv-tts/bin/python tts_kokoro.py \
        --voix bf_emma --sortie sortie.wav \
        --segments segments.json --timings timings.json

Avec --segments ([{"id", "en"}]), chaque segment est synthétisé à part
(découpé en blocs internes s'il est long) et --timings reçoit
[{"id", "startMs", "endMs"}], calculés sur les échantillons produits et
les silences insérés : la piste Kokoro a sa propre timeline (v1.2 § 6.1).
Sinon, le texte est découpé en blocs de phrases (ancien mode).
La progression est imprimée sur stdout sous la forme « PROGRESSION i/n ».
"""

import argparse
import json
import os
import re
import sys
import time

DOSSIER = os.path.dirname(os.path.abspath(__file__))
CHEMIN_MODELE = os.path.join(DOSSIER, "modeles_tts", "kokoro-v1.0.onnx")
CHEMIN_VOIX = os.path.join(DOSSIER, "modeles_tts", "voices-v1.0.bin")
TAILLE_BLOC = 300          # caractères par bloc (limite phonèmes Kokoro)
SILENCE_ENTRE_BLOCS = 0.1 # seconde
SILENCE_ENTRE_SEGMENTS = 0.2  # seconde, après chaque segment
TAUX = 24000               # échantillons par seconde (Kokoro)


def decouper_texte(texte, taille=TAILLE_BLOC):
    """Découpe en blocs de ~taille caractères, sans couper une phrase."""
    phrases = re.split(r"(?<=[.!?])\s+", " ".join(texte.split()).strip())
    blocs, courant = [], ""

    def ajouter(morceau):
        nonlocal courant
        if courant and len(courant) + len(morceau) + 1 > taille:
            blocs.append(courant)
            courant = morceau
        else:
            courant = f"{courant} {morceau}".strip()

    for phrase in phrases:
        if len(phrase) > taille:
            # Phrase très longue : coupe aux virgules puis brutalement aux mots
            for morceau in re.split(r"(?<=[,;:])\s+", phrase):
                while len(morceau) > taille:
                    ajouter(morceau[:taille])
                    morceau = morceau[taille:]
                if morceau:
                    ajouter(morceau)
        else:
            ajouter(phrase)
    if courant:
        blocs.append(courant)
    return [b for b in blocs if b.strip()]


def calculer_timings(segments_blocs, taux=TAUX,
                     silence_bloc=SILENCE_ENTRE_BLOCS,
                     silence_segment=SILENCE_ENTRE_SEGMENTS):
    """Timings d'une piste construite segment par segment.

    segments_blocs : [(id, [nombre d'échantillons de chaque bloc])].
    Dans un segment, les blocs sont séparés par `silence_bloc` ; chaque
    segment est suivi de `silence_segment`. startMs = début de la parole
    du segment, endMs = fin de son dernier bloc (silence final exclu).
    Renvoie (timings, nombre total d'échantillons)."""
    silence_b = int(taux * silence_bloc)
    silence_s = int(taux * silence_segment)
    curseur, timings = 0, []
    for identifiant, blocs in segments_blocs:
        debut = curseur
        for i, n in enumerate(blocs):
            if i:
                curseur += silence_b
            curseur += n
        timings.append({"id": identifiant,
                        "startMs": round(debut * 1000 / taux),
                        "endMs": round(curseur * 1000 / taux)})
        curseur += silence_s
    return timings, curseur


def synthetiser_segments(kokoro, segments, voix, vitesse, langue):
    """Synthétise chaque segment ; renvoie (morceaux audio, timings)."""
    import numpy as np
    morceaux, segments_blocs = [], []
    total = len(segments)
    for numero, segment in enumerate(segments, 1):
        tailles = []
        for i, bloc in enumerate(decouper_texte(segment["en"])):
            if i:
                morceaux.append(np.zeros(int(TAUX * SILENCE_ENTRE_BLOCS)))
            audio, _ = kokoro.create(bloc, voice=voix, speed=vitesse, lang=langue)
            morceaux.append(audio)
            tailles.append(len(audio))
        morceaux.append(np.zeros(int(TAUX * SILENCE_ENTRE_SEGMENTS)))
        segments_blocs.append((segment["id"], tailles))
        print(f"PROGRESSION {numero}/{total}", flush=True)
    timings, _ = calculer_timings(segments_blocs)
    return morceaux, timings


def main():
    analyseur = argparse.ArgumentParser()
    analyseur.add_argument("texte", nargs="?", help="fichier texte à synthétiser")
    analyseur.add_argument("--segments", help="JSON [{id, en}] : synthèse segment par segment")
    analyseur.add_argument("--timings", help="JSON produit [{id, startMs, endMs}] (avec --segments)")
    analyseur.add_argument("--voix", default="bf_emma")
    analyseur.add_argument("--vitesse", type=float, default=1.0)
    analyseur.add_argument("--sortie", required=True, help="fichier .wav produit")
    args = analyseur.parse_args()
    if bool(args.segments) == bool(args.texte) or bool(args.segments) != bool(args.timings):
        print("ERREUR indiquer un texte, ou --segments avec --timings", flush=True)
        sys.exit(1)

    if not os.path.exists(CHEMIN_MODELE):
        print("ERREUR modèle Kokoro introuvable dans modeles_tts/ (voir README)",
              flush=True)
        sys.exit(1)

    if args.segments:
        with open(args.segments, encoding="utf-8") as f:
            segments = [s for s in json.load(f) if (s.get("en") or "").strip()]
        if not segments:
            print("ERREUR aucun segment anglais", flush=True)
            sys.exit(1)
    else:
        with open(args.texte, encoding="utf-8") as f:
            blocs = decouper_texte(f.read())
        if not blocs:
            print("ERREUR texte vide", flush=True)
            sys.exit(1)

    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    # Voix britanniques (bf_/bm_) : phonétique en-gb, sinon américaine
    langue = "en-gb" if args.voix.startswith("b") else "en-us"
    kokoro = Kokoro(CHEMIN_MODELE, CHEMIN_VOIX)
    if args.segments:
        morceaux, timings = synthetiser_segments(kokoro, segments, args.voix,
                                                 args.vitesse, langue)
        with open(args.timings, "w", encoding="utf-8") as f:
            json.dump(timings, f, ensure_ascii=False)
    else:
        morceaux = []
        total = len(blocs)
        for i, bloc in enumerate(blocs, 1):
            audio, _ = kokoro.create(bloc, voice=args.voix,
                                     speed=args.vitesse, lang=langue)
            morceaux.append(audio)
            morceaux.append(np.zeros(int(TAUX * SILENCE_ENTRE_BLOCS)))
            print(f"PROGRESSION {i}/{total}", flush=True)

    sf.write(args.sortie, np.concatenate(morceaux), TAUX)
    duree = sum(len(m) for m in morceaux) / TAUX
    print(f"OK {duree:.0f}s {args.sortie}", flush=True)


if __name__ == "__main__":
    main()
