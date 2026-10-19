# -*- coding: utf-8 -*-
"""Validation stricte du contrat d'enrichissement vocabulaire V1."""

import json
import re


TRANSLATION_STATUSES = {
    "correct", "incomplete", "incorrect_as_standalone", "incorrect", "ambiguous",
}
COLLOCATION_KINDS = {
    "collocation", "grammar_pattern", "phrasal_verb", "idiom", "expression",
}
MODALS = {"can", "could", "may", "might", "must", "shall", "should", "will", "would"}
MAX_RESPONSE_SIZE = 1_000_000


def extraire_json(texte):
    propre = str(texte or "").strip()
    if len(propre.encode("utf-8")) > MAX_RESPONSE_SIZE:
        return None, "La réponse dépasse 1 Mo."
    bloc = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", propre, re.DOTALL)
    if bloc:
        propre = bloc.group(1)
    try:
        return json.loads(propre), None
    except (TypeError, ValueError) as erreur:
        return None, f"JSON invalide : {erreur}"


def _texte(valeur, chemin, erreurs, maximum=500, nullable=False):
    if nullable and valeur is None:
        return None
    if not isinstance(valeur, str):
        erreurs.append(f"{chemin} doit être une chaîne")
        return ""
    if not valeur.strip():
        erreurs.append(f"{chemin} est vide")
    if len(valeur) > maximum:
        erreurs.append(f"{chemin} dépasse {maximum} caractères")
    return valeur


def _valider_sens(valeur, chemin, erreurs):
    if not isinstance(valeur, list) or not 1 <= len(valeur) <= 3:
        erreurs.append(f"{chemin} doit contenir de 1 à 3 sens")
        return [], set()
    resultat, cles = [], set()
    for index, sens in enumerate(valeur):
        prefixe = f"{chemin}[{index}]"
        if not isinstance(sens, dict):
            erreurs.append(f"{prefixe} doit être un objet")
            continue
        cle = _texte(sens.get("senseKey"), prefixe + ".senseKey", erreurs, 100).strip()
        if cle in cles:
            erreurs.append(f"{prefixe}.senseKey est dupliqué")
        cles.add(cle)
        pos = _texte(sens.get("partOfSpeech"), prefixe + ".partOfSpeech", erreurs, 40).strip()
        resultat.append({
            "senseKey": cle,
            "partOfSpeech": pos,
            "translation": _texte(sens.get("translation"), prefixe + ".translation", erreurs, 240),
            "exampleEn": _texte(sens.get("exampleEn"), prefixe + ".exampleEn", erreurs, 400),
            "exampleFr": _texte(sens.get("exampleFr"), prefixe + ".exampleFr", erreurs, 400),
        })
    return resultat, cles


def _valider_collocations(valeur, chemin, cles_sens, erreurs):
    if not isinstance(valeur, list) or len(valeur) > 4:
        erreurs.append(f"{chemin} doit contenir de 0 à 4 éléments")
        return []
    resultat, doublons = [], set()
    for index, item in enumerate(valeur):
        prefixe = f"{chemin}[{index}]"
        if not isinstance(item, dict):
            erreurs.append(f"{prefixe} doit être un objet")
            continue
        en = _texte(item.get("en"), prefixe + ".en", erreurs, 200)
        fr = _texte(item.get("fr"), prefixe + ".fr", erreurs, 240)
        kind = _texte(item.get("kind"), prefixe + ".kind", erreurs, 40).strip()
        cle = _texte(item.get("senseKey"), prefixe + ".senseKey", erreurs, 100).strip()
        if kind not in COLLOCATION_KINDS:
            autorises = ", ".join(sorted(COLLOCATION_KINDS))
            erreurs.append(f"{prefixe}.kind non autorisé : {kind} (attendus : {autorises})")
        if cle not in cles_sens:
            erreurs.append(f"{prefixe}.senseKey ne référence aucun sens")
        doublon = (en.casefold(), kind, cle)
        if doublon in doublons:
            erreurs.append(f"{prefixe} duplique une construction existante")
        doublons.add(doublon)
        resultat.append({"en": en, "fr": fr, "kind": kind, "senseKey": cle})
    return resultat


def _valider_entree(brute, source, index):
    erreurs, avertissements = [], []
    chemin = f"entries[{index}]"
    if not isinstance(brute, dict):
        return None, [f"{chemin} doit être un objet"], []
    identifiant = _texte(brute.get("id"), chemin + ".id", erreurs, 120)
    attendus = {
        "originalWord": str(source.get("word", "")),
        "originalTranslation": str(source.get("translation", "")),
        "originalType": str(source.get("type", "")),
    }
    origines = {}
    for champ, attendu in attendus.items():
        origines[champ] = _texte(brute.get(champ), f"{chemin}.{champ}", erreurs, 400)
        if origines[champ] != attendu:
            erreurs.append(f"{chemin}.{champ} diffère exactement de la donnée source")
    lemma = _texte(brute.get("lemma"), chemin + ".lemma", erreurs, 160)
    display = _texte(brute.get("displayForm"), chemin + ".displayForm", erreurs, 180)
    pos = _texte(brute.get("partOfSpeech"), chemin + ".partOfSpeech", erreurs, 40).strip()
    traduction = _texte(brute.get("primaryTranslation"), chemin + ".primaryTranslation", erreurs, 300)
    statut = _texte(brute.get("translationStatus"), chemin + ".translationStatus", erreurs, 40).strip()
    if statut not in TRANSLATION_STATUSES:
        erreurs.append(f"{chemin}.translationStatus non autorisé : {statut}")
    revue = brute.get("reviewRequired")
    if not isinstance(revue, bool):
        erreurs.append(f"{chemin}.reviewRequired doit être booléen")
        revue = True
    note = _texte(brute.get("reviewNote"), chemin + ".reviewNote", erreurs, 600, nullable=True)
    sens, cles = _valider_sens(brute.get("senses"), chemin + ".senses", erreurs)
    collocations = _valider_collocations(
        brute.get("collocations"), chemin + ".collocations", cles, erreurs)

    source_type = str(source.get("type", "")).replace(" ", "_")
    if pos != source_type:
        avertissements.append("La catégorie grammaticale principale change.")
        revue = True
    if lemma.casefold() in MODALS or pos == "modal_verb":
        if display.casefold().startswith("to "):
            erreurs.append(f"{chemin}.displayForm ne doit pas ajouter « to » à un modal")
    elif pos in {"verb", "phrasal_verb"} and not display.casefold().startswith("to "):
        avertissements.append("La forme pédagogique du verbe ne commence pas par « to ».")
        revue = True
    if sens and traduction.casefold() not in {s["translation"].casefold() for s in sens}:
        avertissements.append("La traduction principale ne correspond exactement à aucun sens.")
    if avertissements:
        revue = True
    normalisee = {
        "id": identifiant, **origines, "lemma": lemma, "displayForm": display,
        "partOfSpeech": pos, "primaryTranslation": traduction,
        "translationStatus": statut, "reviewRequired": revue,
        "reviewNote": note, "senses": sens, "collocations": collocations,
    }
    return normalisee, erreurs, avertissements


def valider_reponse(texte, lot):
    """Valide une réponse et conserve les entrées valides d'un lot incomplet."""
    objet, erreur = extraire_json(texte)
    if erreur:
        return {"entries": [], "errors": [erreur], "missing": lot["ids"], "extra": []}
    if not isinstance(objet, dict):
        return {"entries": [], "errors": ["La racine doit être un objet."], "missing": lot["ids"], "extra": []}
    erreurs_globales = []
    if objet.get("schemaVersion") != 1:
        erreurs_globales.append("schemaVersion doit être le nombre 1.")
    if objet.get("batchId") != lot["batchId"]:
        erreurs_globales.append("batchId ne correspond pas au lot actif.")
    brutes = objet.get("entries")
    if not isinstance(brutes, list):
        return {"entries": [], "errors": erreurs_globales + ["entries doit être une liste."], "missing": lot["ids"], "extra": []}
    if erreurs_globales:
        return {"entries": [], "errors": erreurs_globales,
                "missing": lot["ids"], "extra": []}
    sources = {entree["id"]: entree for entree in lot["sourceEntries"]}
    vus, valides, erreurs, extras = set(), [], list(erreurs_globales), []
    for index, brute in enumerate(brutes):
        identifiant = str(brute.get("id", "")) if isinstance(brute, dict) else ""
        if identifiant in vus:
            erreurs.append(f"entries[{index}].id est dupliqué : {identifiant}")
            continue
        vus.add(identifiant)
        if identifiant not in sources:
            extras.append(identifiant)
            erreurs.append(f"entries[{index}].id est étranger au lot : {identifiant}")
            continue
        entree, erreurs_entree, avertissements = _valider_entree(brute, sources[identifiant], index)
        if erreurs_entree:
            contexte = f"{sources[identifiant].get('word')} ({identifiant})"
            erreurs.extend(f"{contexte} — {message}" for message in erreurs_entree)
        else:
            valides.append({"id": identifiant, "proposed": entree,
                             "warnings": avertissements})
    manquants = [identifiant for identifiant in lot["ids"] if identifiant not in vus]
    if manquants:
        erreurs.append(f"{len(manquants)} entrée(s) manquante(s) dans la réponse.")
    return {"entries": valides, "errors": erreurs,
            "missing": manquants, "extra": extras}
