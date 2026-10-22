"""Dictée du guide : des unités de 3 à 25 mots, horodatées, prises dans les segments du passage.

Un segment regroupe plusieurs phrases (~220 caractères, parfois deux intervenants) : trop long pour
l'oreille. On repart des phrases d'origine (sous-titres, avec l'heure de chaque mot quand YouTube la
donne) ; à défaut (voix de synthèse, ancien fichier), le segment est recoupé sur la ponctuation et
horodaté au prorata des caractères. Une phrase trop longue est coupée sur une virgule.
"""
import re

MOTS_MIN, MOTS_MAX = 3, 25
UNITES_MAX = 100
_FIN_DE_PHRASE = re.compile(r'(?<=[.!?…])\s+')
_PAUSE = (',', ';', ':', '—', '–')


def _normaliser(texte):
    return ' '.join(texte.split())


def _prorata(textes, debut, fin):
    """Morceaux consécutifs horodatés selon leur part du texte."""
    total, cumul, position, resultat = sum(len(t) for t in textes) or 1, 0, debut, []
    for texte in textes:
        cumul += len(texte)
        borne = debut + round((fin - debut) * cumul / total)
        resultat.append({'text': texte, 'startMs': position, 'endMs': borne})
        position = borne
    return resultat


def _phrases(segment):
    """Phrases d'origine si elles recomposent exactement le segment, sinon découpage sur la ponctuation."""
    phrases = segment.get('phrases') or []
    if phrases and _normaliser(' '.join(p['text'] for p in phrases)) == _normaliser(segment['text']):
        return [{'text': _normaliser(p['text']), 'startMs': p['startMs'], 'endMs': p['endMs'],
                 **({'wordStarts': p['wordStarts']} if len(p.get('wordStarts') or []) == len(p['text'].split()) else {})}
                for p in phrases]
    textes = [t for t in (_normaliser(x) for x in _FIN_DE_PHRASE.split(segment['text'])) if t]
    return _prorata(textes, segment['startMs'], segment['endMs'])


def _couper(phrase):
    """Au-delà de 25 mots : coupe sur la pause la plus proche du milieu (sinon au milieu), récursivement."""
    mots = phrase['text'].split()
    if len(mots) <= MOTS_MAX:
        return [phrase]
    milieu = len(mots) / 2
    pauses = [i for i in range(MOTS_MIN, len(mots) - MOTS_MIN + 1) if mots[i - 1].endswith(_PAUSE)]
    coupe = min(pauses, key=lambda i: abs(i - milieu)) if pauses else round(milieu)
    gauche, droite = ' '.join(mots[:coupe]), ' '.join(mots[coupe:])
    heures = phrase.get('wordStarts')
    if heures:
        a = {'text': gauche, 'startMs': phrase['startMs'], 'endMs': heures[coupe], 'wordStarts': heures[:coupe]}
        b = {'text': droite, 'startMs': heures[coupe], 'endMs': phrase['endMs'], 'wordStarts': heures[coupe:]}
    else:
        a, b = _prorata([gauche, droite], phrase['startMs'], phrase['endMs'])
    return _couper(a) + _couper(b)


def _regrouper_courtes(morceaux):
    """Une phrase de moins de 3 mots rejoint sa voisine (la précédente d'abord), sinon elle est écartée."""
    resultat = []
    for m in morceaux:
        if resultat and (len(m['text'].split()) < MOTS_MIN or len(resultat[-1]['text'].split()) < MOTS_MIN) \
                and len(resultat[-1]['text'].split()) + len(m['text'].split()) <= MOTS_MAX:
            resultat[-1] = {'text': resultat[-1]['text'] + ' ' + m['text'], 'startMs': resultat[-1]['startMs'], 'endMs': m['endMs']}
        else:
            resultat.append(m)
    return [m for m in resultat if len(m['text'].split()) >= MOTS_MIN]


def unites(segments):
    """[{id, segmentId, text, startMs, endMs}] pour les segments horodatés donnés (le passage), dans l'ordre."""
    resultat, dernier_debut = [], -1
    for segment in segments:
        if segment.get('startMs') is None or segment.get('endMs') is None:
            continue
        morceaux = [c for p in _phrases(segment) for c in _couper(p)]
        texte = _normaliser(segment['text'])
        for m in _regrouper_courtes(morceaux):
            debut, fin = max(m['startMs'], segment['startMs']), min(m['endMs'], segment['endMs'])
            if m['text'] not in texte or fin <= debut or debut <= dernier_debut:
                continue
            resultat.append({'id': f'd{len(resultat) + 1:03d}', 'segmentId': segment['id'], 'text': m['text'],
                             'startMs': debut, 'endMs': fin})
            dernier_debut = debut
            if len(resultat) == UNITES_MAX:
                return resultat
    return resultat
