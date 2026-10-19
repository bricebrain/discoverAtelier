# -*- coding: utf-8 -*-
"""Configuration locale et non versionnee des API de vocabulaire."""

import json
import os
from pathlib import Path


CHEMIN = Path(__file__).with_name("config_ia.json")
DEFAUTS = {
    "generatorModel": "gemini-3.1-flash-lite",
    "auditorModel": "gpt-6-luna",
    "batchSize": 20,
    "maxRetries": 2,
    "autoPublish": True,
}


def charger():
    donnees = {}
    if CHEMIN.exists():
        try:
            donnees = json.loads(CHEMIN.read_text(encoding="utf-8"))
        except (OSError, ValueError) as erreur:
            raise RuntimeError(f"Configuration IA illisible : {erreur}") from erreur
    config = {**DEFAUTS, **donnees}
    config["openaiApiKey"] = os.environ.get("OPENAI_API_KEY") or config.get("openaiApiKey", "")
    config["geminiApiKey"] = os.environ.get("GEMINI_API_KEY") or config.get("geminiApiKey", "")
    config["batchSize"] = min(max(int(config["batchSize"]), 1), 20)
    config["maxRetries"] = min(max(int(config.get("maxRetries", 2)), 0), 4)
    config["autoPublish"] = bool(config.get("autoPublish", True))
    return config


def enregistrer(donnees):
    precedente = charger()
    resultat = dict(DEFAUTS)
    for cle in ("generatorModel", "auditorModel"):
        valeur = str(donnees.get(cle) or precedente.get(cle) or "").strip()
        if not valeur or len(valeur) > 120:
            raise ValueError(f"{cle} est invalide.")
        resultat[cle] = valeur
    for cle, variable in (("openaiApiKey", "OPENAI_API_KEY"),
                          ("geminiApiKey", "GEMINI_API_KEY")):
        nouvelle = str(donnees.get(cle) or "").strip()
        resultat[cle] = nouvelle or precedente.get(cle, "")
        if os.environ.get(variable):
            resultat[cle] = ""
    resultat["batchSize"] = min(max(int(donnees.get("batchSize", precedente["batchSize"])), 1), 20)
    resultat["maxRetries"] = min(max(int(donnees.get("maxRetries", 2)), 0), 4)
    resultat["autoPublish"] = bool(donnees.get("autoPublish", True))
    CHEMIN.write_text(json.dumps(resultat, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    try:
        os.chmod(CHEMIN, 0o600)
    except OSError:
        pass
    return etat(charger())


def etat(config=None):
    config = config or charger()
    return {
        "openaiConfigured": bool(config.get("openaiApiKey")),
        "geminiConfigured": bool(config.get("geminiApiKey")),
        "generatorModel": config["generatorModel"],
        "auditorModel": config["auditorModel"],
        "batchSize": config["batchSize"],
        "maxRetries": config["maxRetries"],
        "autoPublish": config["autoPublish"],
    }
