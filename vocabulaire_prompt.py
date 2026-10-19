# -*- coding: utf-8 -*-
"""Construction du prompt versionné d'enrichissement lexical."""

import json


MODELE = """Tu es lexicographe et enseignant d'anglais britannique pour francophones (A1–C1).

MISSION
Audite et enrichis exactement les entrées de vocabulaire fournies. Le contexte d'origine est parfois absent : n'invente pas de contexte source.

OBJECTIFS
1. Classe la traduction : correct, incomplete, incorrect_as_standalone, incorrect ou ambiguous.
2. Garde lemma sans « to ». displayForm peut être « to + verbe » pour un verbe lexical, jamais pour un modal ou une forme conjuguée.
3. Donne une catégorie grammaticale anglaise précise dans partOfSpeech. Toute catégorie pertinente est autorisée (par exemple noun, verb, conjunction, pronoun, determiner, interjection ou particle).
4. Donne 1 sens principal et jusqu'à 2 autres sens uniquement s'ils sont utiles.
5. Pour chaque sens, fournis une phrase EN britannique courte et sa traduction FR fidèle.
6. Propose au maximum 4 constructions utiles : collocation, grammar_pattern, phrasal_verb, idiom ou expression.
7. Préserve exactement id, originalWord, originalTranslation et originalType.
8. En cas de changement de catégorie ou d'incertitude, mets reviewRequired=true et explique reviewNote.
9. Conserve le niveau CEFR fourni. Ne supprime, n'ajoute ni ne fusionne aucune entrée.

FORMAT DE SORTIE
Retourne EXCLUSIVEMENT un objet JSON valide, sans Markdown ni commentaire :
{"schemaVersion":1,"batchId":"<identique>","entries":[{"id":"string","originalWord":"string","originalTranslation":"string","originalType":"string","lemma":"string","displayForm":"string","partOfSpeech":"string","primaryTranslation":"string","translationStatus":"correct|incomplete|incorrect_as_standalone|incorrect|ambiguous","reviewRequired":false,"reviewNote":null,"senses":[{"senseKey":"string","partOfSpeech":"string","translation":"string","exampleEn":"string","exampleFr":"string"}],"collocations":[{"en":"string","fr":"string","kind":"collocation|grammar_pattern|phrasal_verb|idiom|expression","senseKey":"string"}]}]}

AUTO-VÉRIFICATION
Vérifie l'unicité et l'ordre des id, le nombre d'entrées, les références senseKey, les traductions françaises et la validité du JSON.

DONNÉES DU LOT
<JSON_DU_LOT>
"""


def source_depuis_mot(mot):
    return {
        "id": str(mot.get("id")),
        "word": str(mot.get("mot") or ""),
        "translation": str(mot.get("traduction") or ""),
        "type": str(mot.get("type") or ""),
        "cefr": str(mot.get("niveau") or ""),
    }


def construire(batch_id, sources):
    payload = {"schemaVersion": 1, "batchId": batch_id, "entries": sources}
    return MODELE.replace(
        "<JSON_DU_LOT>", json.dumps(payload, ensure_ascii=False, indent=2))


def construire_audit(lot, proposition):
    """Demande a un second modele de corriger la proposition, pas de la commenter."""
    sources = {item["id"]: item for item in lot["sourceEntries"]}
    payload = {
        "schemaVersion": 1,
        "batchId": lot["batchId"],
        "sources": [sources[identifiant] for identifiant in lot["ids"]],
        "candidate": proposition,
    }
    return """Tu es le controle final d'un referentiel pedagogique anglais-francais.

Verifie chaque entree candidate puis RENVOIE UNE VERSION CORRIGEE COMPLETE.
Tu dois notamment controler la traduction en contexte, la categorie grammaticale,
le lemme, la forme avec ou sans « to », les sens reellement utiles, la fidelite des
exemples bilingues, les collocations et leurs senseKey. Corrige silencieusement toute
erreur. N'ajoute et ne supprime aucune entree. Preserve exactement les quatre champs
id, originalWord, originalTranslation et originalType. Conserve batchId et schemaVersion.
Le resultat doit contenir uniquement le JSON final conforme au schema impose.

DONNEES A AUDITER
""" + json.dumps(payload, ensure_ascii=False, indent=2)
