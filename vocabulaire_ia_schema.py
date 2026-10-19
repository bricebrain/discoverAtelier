# -*- coding: utf-8 -*-
"""Schema de sortie commun aux fournisseurs d'IA."""


def _objet(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": required or list(properties),
        "additionalProperties": False,
    }


SENS = _objet({
    "senseKey": {"type": "string"},
    "partOfSpeech": {"type": "string"},
    "translation": {"type": "string"},
    "exampleEn": {"type": "string"},
    "exampleFr": {"type": "string"},
})

COLLOCATION = _objet({
    "en": {"type": "string"},
    "fr": {"type": "string"},
    "kind": {"type": "string", "enum": [
        "collocation", "grammar_pattern", "phrasal_verb", "idiom", "expression",
    ]},
    "senseKey": {"type": "string"},
})

ENTREE = _objet({
    "id": {"type": "string"},
    "originalWord": {"type": "string"},
    "originalTranslation": {"type": "string"},
    "originalType": {"type": "string"},
    "lemma": {"type": "string"},
    "displayForm": {"type": "string"},
    "partOfSpeech": {"type": "string"},
    "primaryTranslation": {"type": "string"},
    "translationStatus": {"type": "string", "enum": [
        "correct", "incomplete", "incorrect_as_standalone", "incorrect", "ambiguous",
    ]},
    "reviewRequired": {"type": "boolean"},
    "reviewNote": {"type": ["string", "null"]},
    "senses": {"type": "array", "minItems": 1, "maxItems": 3, "items": SENS},
    "collocations": {"type": "array", "maxItems": 4, "items": COLLOCATION},
})

SCHEMA_LOT = _objet({
    "schemaVersion": {"type": "integer", "enum": [1]},
    "batchId": {"type": "string"},
    "entries": {"type": "array", "minItems": 1, "maxItems": 20, "items": ENTREE},
})


def schema_pour_gemini(schema):
    """Evite l'explosion des contraintes des tableaux imbriques cote Gemini.

    Les bornes restent imposees par le prompt et le validateur local ; le
    schema strict original est conserve pour OpenAI.
    """
    if isinstance(schema, dict):
        return {cle: schema_pour_gemini(valeur)
                for cle, valeur in schema.items()
                if cle not in {"minItems", "maxItems"}}
    if isinstance(schema, list):
        return [schema_pour_gemini(item) for item in schema]
    return schema
