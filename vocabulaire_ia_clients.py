# -*- coding: utf-8 -*-
"""Clients HTTP minimaux pour les sorties structurees OpenAI et Gemini."""

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

from vocabulaire_ia_schema import schema_pour_gemini


OPENAI_URL = "https://api.openai.com/v1/responses"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
RAISONNEMENT_OPENAI = "low"


def _poster(url, payload, entetes, timeout=300):
    requete = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **entetes}, method="POST")
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        detail = erreur.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"API HTTP {erreur.code} : {detail}") from erreur
    except urllib.error.URLError as erreur:
        raise RuntimeError(f"API inaccessible : {erreur.reason}") from erreur
    except (OSError, http.client.HTTPException) as erreur:
        raise RuntimeError(f"Connexion API interrompue : {erreur}") from erreur
    except (ValueError, UnicodeDecodeError) as erreur:
        raise RuntimeError("L'API a renvoye une reponse illisible.") from erreur


def _texte_openai(objet):
    direct = objet.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    morceaux = []
    for sortie in objet.get("output") or []:
        for contenu in sortie.get("content") or []:
            if contenu.get("type") in {"output_text", "text"} and contenu.get("text"):
                morceaux.append(contenu["text"])
    if not morceaux:
        raise RuntimeError("OpenAI n'a renvoye aucun JSON exploitable.")
    return "".join(morceaux)


def generer_openai(prompt, modele, cle, schema):
    if not cle:
        raise RuntimeError("La cle OpenAI n'est pas configuree.")
    objet = _poster(OPENAI_URL, {
        "model": modele,
        "input": prompt,
        "reasoning": {"effort": RAISONNEMENT_OPENAI},
        "max_output_tokens": 30000,
        "text": {"format": {
            "type": "json_schema", "name": "vocabulary_batch",
            "strict": True, "schema": schema,
        }},
    }, {"Authorization": f"Bearer {cle}"})
    usage = objet.get("usage") or {}
    return {
        "text": _texte_openai(objet), "provider": "openai", "model": modele,
        "inputTokens": usage.get("input_tokens", 0),
        "outputTokens": usage.get("output_tokens", 0),
    }


def _texte_gemini(objet):
    morceaux = []
    for candidat in objet.get("candidates") or []:
        for partie in (candidat.get("content") or {}).get("parts") or []:
            if isinstance(partie.get("text"), str):
                morceaux.append(partie["text"])
    if not morceaux:
        blocage = (objet.get("promptFeedback") or {}).get("blockReason")
        suffixe = f" ({blocage})" if blocage else ""
        raise RuntimeError("Gemini n'a renvoye aucun JSON exploitable" + suffixe + ".")
    return "".join(morceaux)


def generer_gemini(prompt, modele, cle, schema):
    if not cle:
        raise RuntimeError("La cle Gemini n'est pas configuree.")
    url = GEMINI_URL.format(model=urllib.parse.quote(modele, safe=""))
    objet = _poster(url, {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 30000,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema_pour_gemini(schema),
        },
    }, {"x-goog-api-key": cle})
    usage = objet.get("usageMetadata") or {}
    return {
        "text": _texte_gemini(objet), "provider": "gemini", "model": modele,
        "inputTokens": usage.get("promptTokenCount", 0),
        "outputTokens": (usage.get("candidatesTokenCount", 0) or 0)
                        + (usage.get("thoughtsTokenCount", 0) or 0),
    }


def generer(provider, prompt, modele, cle, schema):
    try:
        if provider == "openai":
            return generer_openai(prompt, modele, cle, schema)
        if provider == "gemini":
            return generer_gemini(prompt, modele, cle, schema)
        raise ValueError(f"Fournisseur IA inconnu : {provider}")
    except RuntimeError as erreur:
        raise RuntimeError(f"{provider} ({modele}) — {erreur}") from erreur
