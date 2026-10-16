#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Génération d'audio anglais avec Kokoro TTS (modèle local).

Exécuté par convertisseur_web.py via l'environnement dédié
`venv-tts` (Python 3.12 — kokoro-onnx exige un onnxruntime récent).

Usage :
    venv-tts/bin/python tts_kokoro.py \
        --voix bf_emma --sortie sortie.wav texte.txt

Le texte est découpé en blocs de phrases ; la progression est imprimée
sur stdout sous la forme « PROGRESSION i/n » (lue par l'atelier).
"""

import argparse
import os
import re
import sys
import time

DOSSIER = os.path.dirname(os.path.abspath(__file__))
CHEMIN_MODELE = os.path.join(DOSSIER, "modeles_tts", "kokoro-v1.0.onnx")
CHEMIN_VOIX = os.path.join(DOSSIER, "modeles_tts", "voices-v1.0.bin")
TAILLE_BLOC = 300          # caractères par bloc (limite phonèmes Kokoro)
SILENCE_ENTRE_BLOCS = 0.15 # seconde


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


def main():
    analyseur = argparse.ArgumentParser()
    analyseur.add_argument("texte", help="fichier texte à synthétiser")
    analyseur.add_argument("--voix", default="bf_emma")
    analyseur.add_argument("--vitesse", type=float, default=1.0)
    analyseur.add_argument("--sortie", required=True, help="fichier .wav produit")
    args = analyseur.parse_args()

    if not os.path.exists(CHEMIN_MODELE):
        print("ERREUR modèle Kokoro introuvable dans modeles_tts/ (voir README)",
              flush=True)
        sys.exit(1)

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
    morceaux = []
    total = len(blocs)
    for i, bloc in enumerate(blocs, 1):
        audio, _ = kokoro.create(bloc, voice=args.voix,
                                 speed=args.vitesse, lang=langue)
        morceaux.append(audio)
        morceaux.append(np.zeros(int(24000 * SILENCE_ENTRE_BLOCS)))
        print(f"PROGRESSION {i}/{total}", flush=True)

    sf.write(args.sortie, np.concatenate(morceaux), 24000)
    duree = sum(len(m) for m in morceaux) / 24000
    print(f"OK {duree:.0f}s {args.sortie}", flush=True)


if __name__ == "__main__":
    main()
