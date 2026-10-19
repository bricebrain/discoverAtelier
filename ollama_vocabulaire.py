# -*- coding: utf-8 -*-
"""Client local Ollama pour l'audit du vocabulaire English Fluency."""

import json
import os
import urllib.error
import urllib.request


OLLAMA_URL = "http://127.0.0.1:11434"


def _requete_ollama(chemin, payload=None, timeout=5):
    donnees = (json.dumps(payload, ensure_ascii=False).encode("utf-8")
               if payload is not None else None)
    requete = urllib.request.Request(
        OLLAMA_URL + chemin, data=donnees,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.URLError as erreur:
        raise RuntimeError(
            "Ollama ne répond pas sur le port 11434. Ouvrez l'application Ollama puis réessayez.") from erreur
    except (ValueError, UnicodeDecodeError) as erreur:
        raise RuntimeError("Réponse Ollama invalide.") from erreur


def _priorite(element):
    nom = element["name"].lower()
    if nom.startswith("mistral"):
        return (0, nom)
    if nom.startswith("deepseek-r1") and ("7b" in nom or "8b" in nom):
        return (1, nom)
    if nom.startswith("gemma3"):
        return (2, nom)
    if "coder" in nom:
        return (4, nom)
    return (3, nom)


def etat():
    """Liste les modèles locaux sans lancer ni télécharger quoi que ce soit."""
    try:
        objet = _requete_ollama("/api/tags")
    except RuntimeError as erreur:
        return {"available": False,
                "installed": os.path.exists("/Applications/Ollama.app"),
                "models": [], "message": str(erreur)}
    modeles = []
    for modele in objet.get("models", []):
        nom = modele.get("name") or modele.get("model")
        if nom:
            modeles.append({"name": nom, "size": modele.get("size"),
                            "parameterSize": (modele.get("details") or {}).get("parameter_size")})
    modeles.sort(key=_priorite)
    return {"available": True, "installed": True, "models": modeles,
            "message": (f"{len(modeles)} modèle(s) disponible(s)"
                        if modeles else "Ollama fonctionne, mais aucun modèle n'est téléchargé.")}


def generer(prompt, modele):
    disponibles = {m["name"] for m in etat().get("models", [])}
    modele = str(modele or "").strip()
    if not modele or modele not in disponibles:
        raise ValueError("Sélectionnez un modèle Ollama disponible.")
    objet = _requete_ollama("/api/generate", {
        "model": modele, "prompt": prompt, "stream": False, "format": "json",
        "options": {"temperature": 0}, "keep_alive": "5m",
    }, timeout=900)
    texte = objet.get("response") if isinstance(objet, dict) else None
    if not isinstance(texte, str) or not texte.strip():
        raise RuntimeError("Ollama n'a renvoyé aucune réponse exploitable.")
    return {"text": texte, "model": modele,
            "durationNs": objet.get("total_duration"),
            "outputTokens": objet.get("eval_count")}
