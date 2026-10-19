# -*- coding: utf-8 -*-
"""Adaptateur de publication des enrichissements vers le Worker."""

import json
import urllib.parse

import bundles


def publier(lot, partiel=False):
    entrees = [item["proposed"] for item in lot.get("entries", {}).values()
               if item.get("status") == "ready_to_publish"]
    if not entrees:
        raise ValueError("Aucune entrée approuvée à publier.")
    approuvees = sum(item.get("status") == "ready_to_publish"
                     for item in lot.get("entries", {}).values())
    incomplet = bool(lot.get("missing") or lot.get("errors")
                     or approuvees != len(lot.get("ids", [])))
    if incomplet and not partiel:
        raise ValueError("Le lot est incomplet. Autorisez explicitement la publication partielle.")
    config, erreur = bundles.charger_config_import()
    if erreur:
        raise RuntimeError(erreur)
    batch_id = urllib.parse.quote(lot["batchId"], safe="")
    corps = bundles._requete_worker(
        f"{config['workerUrl']}/admin/vocabulary/batches/{batch_id}/publish",
        donnees=json.dumps({"schemaVersion": 1, "batchId": lot["batchId"],
                            "entries": entrees}).encode("utf-8"),
        entetes={"Authorization": f"Bearer {config['apiSecret']}",
                  "Content-Type": "application/json"}, methode="POST")
    try:
        resultat = json.loads(corps)
    except ValueError as erreur_json:
        raise RuntimeError(f"réponse de publication invalide : {erreur_json}") from erreur_json
    if not isinstance(resultat, dict) or not resultat.get("ok"):
        raise RuntimeError("Le Worker n'a pas confirmé la publication.")
    return resultat
