"""Retire les renvois techniques du texte parlé, en conservant leur métadonnée."""
import re


GROUP = re.compile(r'\([^()\[\]]*\)|\[[^()\[\]]*\]')


def nettoyer_texte(text, source_ids):
    def remplacer(match):
        refs = re.split(r'[,;\s]+', match.group()[1:-1].strip())
        return '' if refs and all(ref in source_ids for ref in refs) else match.group()

    cleaned = GROUP.sub(remplacer, text)
    if cleaned == text:
        return text
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    return re.sub(r'[ \t]+([.,;:!?])', r'\1', cleaned).strip()


def nettoyer_segments(segments, source_ids=None):
    ids = set(source_ids) if source_ids is not None else {
        ref for segment in segments for ref in segment.get('sourceSegments', [])}
    result = []
    for segment in segments:
        clean = dict(segment)
        for field in ('text', 'fr'):
            if field in clean:
                clean[field] = nettoyer_texte(clean[field], ids)
                if not clean[field].strip():
                    raise ValueError('Un paragraphe ne contient que des renvois source.')
        result.append(clean)
    return result
