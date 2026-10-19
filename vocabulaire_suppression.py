# -*- coding: utf-8 -*-
"""Suppression en masse du référentiel distant de vocabulaire."""

import json

import bundles


def supprimer(identifiants, mots_disponibles):
    ids = list(dict.fromkeys(str(i).strip() for i in identifiants if str(i).strip()))
    if not 1 <= len(ids) <= 200:
        raise ValueError("Sélectionnez entre 1 et 200 mots à supprimer.")
    inconnus = [identifiant for identifiant in ids
                if identifiant not in mots_disponibles]
    if inconnus:
        raise ValueError("Mots introuvables : " + ", ".join(inconnus[:10]))

    config, erreur = bundles.charger_config_import()
    if erreur:
        raise RuntimeError(erreur)
    corps = bundles._requete_worker(
        f"{config['workerUrl']}/words",
        donnees=json.dumps({"ids": ids}).encode("utf-8"),
        entetes={"Authorization": f"Bearer {config['apiSecret']}",
                  "Content-Type": "application/json"},
        methode="DELETE")
    try:
        resultat = json.loads(corps)
    except ValueError as erreur_json:
        raise RuntimeError(f"réponse DELETE /words invalide : {erreur_json}") from erreur_json
    if not isinstance(resultat, dict) or resultat.get("deleted") != len(ids):
        raise RuntimeError("Le Worker n'a pas confirmé la suppression complète du lot.")
    return ids, resultat
