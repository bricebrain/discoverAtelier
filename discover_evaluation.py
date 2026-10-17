"""Contrôles locaux de fidélité et de langue ; les heuristiques demandent une relecture, jamais une correction silencieuse."""
import re
import unicodedata


WORD = re.compile(r"[A-Za-zÀ-ÿ]+(?:['’-][A-Za-zÀ-ÿ]+)*")
COMMON_STARTS = set('The A An This That These Those It They We You He She In On At For But And Or However First Second Finally Today There When If Although As After Before While Some Many Most One Two Three Our Their His Her Its To From By With Without So Now'.lower().split())


def mots(texte):
    return WORD.findall(texte)


def normaliser(texte):
    return ''.join(c for c in unicodedata.normalize('NFKD', texte).lower() if not unicodedata.combining(c))


def nombres(texte):
    values = set()
    texte = re.sub(r'(?<=\d)[ \u00a0](?=\d{3}\b)', '', texte)
    for value in re.findall(r'\b\d+(?:[.,]\d+)*', texte):
        if re.fullmatch(r'\d{1,3}(?:[,\.]\d{3})+', value):
            value = value.replace(',', '').replace('.', '')
        else:
            value = value.replace(',', '.')
        values.add(value)
    return values


def entites(texte):
    names = set()
    for phrase in re.split(r'(?<=[.!?])\s+', texte):
        for match in re.finditer(r"\b[A-Z][A-Za-zÀ-ÿ'’-]*(?:\s+[A-Z][A-Za-zÀ-ÿ'’-]*)*\b", phrase):
            value = match.group()
            words = value.split()
            if words and words[0].lower() in COMMON_STARTS:
                words = words[1:]
                value = ' '.join(words)
            if value and (len(words) > 1 or match.start() > 0 or (value.isupper() and len(value) > 1)):
                names.add(re.sub(r"['’]s\b", '', value))
    return names


def valider_script(script, source_ids, style):
    if style == 'dialogue' and {p['speaker'] for p in script['segments']} != {'Host', 'Guest'}:
        raise ValueError('Le dialogue doit faire intervenir Host et Guest.')
    for p in script['segments']:
        if not p['text'].strip() or not p['fr'].strip():
            raise ValueError('Chaque paragraphe exige text et fr non vides.')
        if not p['sourceSegments'] or len(set(p['sourceSegments'])) != len(p['sourceSegments']) or not set(p['sourceSegments']) <= source_ids:
            raise ValueError('Renvois source absents, dupliqués ou inconnus.')
        if (style == 'narration' and p['speaker'] != 'Narrator') or (style == 'dialogue' and p['speaker'] not in ('Host', 'Guest')):
            raise ValueError('Intervenant incompatible avec le style demandé.')


def evaluer(script, sources, options, frequent=None):
    missing_numbers, missing_entities = [], []
    by_id = {s['id']: s['text'] for s in sources}
    for index, p in enumerate(script['segments'], 1):
        cited = ' '.join(by_id[r] for r in p['sourceSegments'])
        missing_numbers += [{'paragraph': index, 'value': n} for n in sorted(nombres(p['text']) - nombres(cited))]
        missing_entities += [{'paragraph': index, 'value': n} for n in sorted(entites(p['text']))
                            if normaliser(n) not in normaliser(cited)]
    text = ' '.join(p['text'] for p in script['segments'])
    sentences = [mots(s) for s in re.split(r'[.!?]+', text) if mots(s)]
    tokens = mots(text)
    vocab = {normaliser(w) for w in script.get('keyVocab', [])}
    names = {normaliser(n) for n in entites(text)}
    off_list = None
    if frequent:
        off_list = [w for w in tokens if normaliser(w) not in frequent | vocab | names]
    language = {'meanSentenceWords': round(sum(map(len, sentences)) / max(1, len(sentences)), 1),
                'longSentenceRatio': round(sum(len(s) > 25 for s in sentences) / max(1, len(sentences)), 3),
                'uncommonWordRatio': round(len(off_list) / max(1, len(tokens)), 3) if off_list is not None else None,
                'frequentVocabularyAvailable': bool(frequent),
                'complexPatterns': sorted(set(re.findall(r'\b(?:would have|could have|might have|had been|has been being|were to)\b', text, re.I)))}
    warnings = []
    if options.get('level') in ('A2', 'B1'):
        if language['meanSentenceWords'] > 18:
            warnings.append('Phrases plus longues que la cible indicative B1.')
        if language['longSentenceRatio'] > .1:
            warnings.append('Plus de 10 % des phrases dépassent 25 mots.')
        if language['uncommonWordRatio'] is not None and language['uncommonWordRatio'] > .1:
            warnings.append('Vocabulaire hors référentiel au-delà de la cible indicative.')
    language['warnings'] = warnings
    return {'verdict': 'review' if missing_numbers or missing_entities or script['tooShortForSubject'] else 'ok',
            'numbersMissingFromSource': missing_numbers, 'entitiesMissingFromSource': missing_entities,
            'tooShortForSubject': script['tooShortForSubject'], 'recommendedMinutes': script['recommendedMinutes'],
            'wordCount': len(tokens), 'language': language}
