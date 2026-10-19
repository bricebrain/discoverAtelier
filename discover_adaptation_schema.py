"""Schémas des sorties Gemini. Références et règles métier contrôlées séparément."""
TEXT = {'type': 'string', 'minLength': 1}
REFS = {'type': 'array', 'items': TEXT, 'minItems': 1}


def objet(props):
    return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}


def liste(item):
    return {'type': 'array', 'items': item}


PLAN = objet({'summary': TEXT, 'speakers': liste(TEXT), 'properNames': liste(TEXT), 'glossary': liste(TEXT)})
EXTRACTION = objet({'items': liste(objet({'type': {'type': 'string', 'enum': ['fact', 'explanation', 'argument', 'example', 'disagreement', 'promotion', 'context']},
                                      'text': TEXT, 'sourceSegments': REFS}))})
PARAGRAPH = objet({'text': TEXT, 'fr': TEXT, 'speaker': {'type': 'string', 'enum': ['Narrator', 'Host', 'Guest']}, 'sourceSegments': REFS})
SCRIPT = objet({'segments': {'type': 'array', 'items': PARAGRAPH, 'minItems': 1},
                'keyVocab': liste(TEXT), 'tooShortForSubject': {'type': 'boolean'},
                'recommendedMinutes': {'type': ['number', 'null']}})
JUDGE = objet({'verdict': {'type': 'string', 'enum': ['ok', 'review', 'rejected']},
               'unsupportedClaims': liste(TEXT), 'omittedKeyPoints': liste(TEXT),
               'lostNuances': liste(TEXT), 'promotionsRemaining': liste(TEXT), 'languageWarnings': liste(TEXT)})

FULL_JUDGE = objet({**JUDGE["properties"], "factChecks": liste(objet({"factIndex": {"type": "integer"}, "presentInScript": {"type": "boolean"}, "reason": TEXT}))})

QUIZ = objet({'questions': {'type': 'array', 'minItems': 3, 'maxItems': 3, 'items': objet({
    'question': {'type': 'string', 'minLength': 1, 'maxLength': 500},
    'choices': {'type': 'array', 'minItems': 3, 'maxItems': 3,
                'items': {'type': 'string', 'minLength': 1, 'maxLength': 300}},
    'correctChoice': {'type': 'integer', 'minimum': 0, 'maximum': 2},
    'explanation': {'type': 'string', 'minLength': 1, 'maxLength': 800},
    'segmentIndex': {'type': 'integer', 'minimum': 0, 'maximum': 99999}})}})
