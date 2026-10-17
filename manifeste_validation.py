"""Contrat Discover : schémas partagés + contraintes entre variantes/fichiers."""
import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


class ErreurManifeste(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def refuser(code):
    raise ErreurManifeste(code)


def contrats():
    return Path(os.environ.get('DISCOVER_CONTRACTS_DIR') or
                Path(__file__).resolve().parent.parent / 'discover-mymind' / 'contracts')


def schema(nom, valeur):
    try:
        from jsonschema import Draft7Validator
    except ImportError as e:
        raise RuntimeError('Installer les dépendances Atelier : pip install -r requirements.txt') from e
    with open(contrats() / (nom + '.schema.json'), encoding='utf-8') as f:
        if not Draft7Validator(json.load(f)).is_valid(valeur):
            refuser('invalid_manifest' if nom == 'manifest' else 'invalid_segments')


def chemin_valide(path):
    return (len(path) <= 180 and re.fullmatch(
        r'[a-zA-Z0-9][a-zA-Z0-9._-]*(/[a-zA-Z0-9][a-zA-Z0-9._-]*)*', path)
        and all(p not in ('.', '..') for p in path.split('/')))


def url_valide(raw, allow_http=False):
    try:
        u = urlsplit(raw.strip())
        host = (u.hostname or '').lower().rstrip('.')
        if (len(raw) > 2048 or (u.scheme != 'https' and not (allow_http and u.scheme == 'http')) or u.username or u.password
                or (u.port and u.port != 443) or not host or '.' not in host
                or host == 'localhost' or host.endswith((
                    '.local', '.internal', '.lan', '.localhost', '.home.arpa', '.intranet', '.corp'))):
            refuser('unsafe_url')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            refuser('unsafe_url')
        if ':' in host or re.search(r'[\x00-\x20\x7f%\\]', host) or re.fullmatch(r'(0x[0-9a-f]+|[0-9]+)(\.(0x[0-9a-f]+|[0-9]+))*', host):
            refuser('unsafe_url')
    except (ValueError, AttributeError):
        refuser('unsafe_url')


def valider_manifeste(m, context=None):
    schema('manifest', m)
    c, variants, files = m['content'], m['variants'], m['files']
    sources = [v for v in variants if v['kind'] == 'source']
    if len(sources) != 1:
        refuser('invalid_source')
    source = sources[0]
    if (source['language'] != c['originalLanguage'] or source.get('cefrLevel') is not None
            or source.get('derivedFrom') is not None):
        refuser('invalid_source')
    keys = [v['key'] for v in variants]
    if len(set(keys)) != len(keys):
        refuser('duplicate_variant')
    if c.get('sourceUrl'):
        url_valide(c['sourceUrl'], c['sourceType'] == 'podcast')
    ref = c.get('sourceRef') or ''
    if ((c['sourceType'] == 'podcast' and not re.fullmatch(r'episode:[0-9a-f]{20}', ref))
            or (c['sourceType'] == 'reflection' and not re.fullmatch(r'reflection:[0-9a-f-]{36}', ref))
            or (c['sourceType'] == 'youtube' and c.get('sourceRef') is not None and not re.fullmatch(r'youtube:[A-Za-z0-9_-]{11}', ref))):
        refuser('invalid_source_ref')
    if sum(f['size'] for f in files.values()) > 300_000_000:
        refuser('publication_too_large')
    used = set()
    for v in variants:
        if v['kind'] == 'faithful_translation' and (
                v.get('derivedFrom') != source['key']
                or v['language'].split('-')[0] == source['language'].split('-')[0]
                or v.get('cefrLevel') is not None):
            refuser('invalid_translation')
        if v['kind'] == 'adaptation' and (
                not v.get('style') or v['language'].split('-')[0] != 'en'
                or v.get('derivedFrom') not in keys or v.get('derivedFrom') == v['key']):
            refuser('invalid_adaptation')
        visited, parent = {v['key']}, v.get('derivedFrom')
        while parent:
            if parent in visited:
                refuser('cyclic_derivation')
            visited.add(parent)
            parent = next((n.get('derivedFrom') for n in variants if n['key'] == parent), None)
        if v.get('coverage', 'full') != 'full' and (
                v['kind'] != 'adaptation' or not v.get('condensation')):
            refuser('invalid_coverage')
        if v.get('coverage', 'full') == 'full' and v.get('condensation'):
            refuser('invalid_coverage')
        path = v['segmentsFile']
        if not chemin_valide(path) or files.get(path, {}).get('contentType') != 'application/json':
            refuser('invalid_files')
        if files[path]['size'] > 5_000_000:
            refuser('segments_too_large')
        used.add(path)
        audio = v.get('audio') or {}
        if audio.get('source') == 'r2':
            path = audio['file']
            if not chemin_valide(path) or files.get(path, {}).get('contentType') != 'audio/mpeg':
                refuser('invalid_files')
            used.add(path)
        if audio.get('source') == 'publisher_stream':
            url_valide(audio['url'], c['sourceType'] == 'podcast')
            if c['sourceType'] != 'podcast' or v['kind'] != 'source' or audio['origin'] != 'original':
                refuser('invalid_stream')
    if any(not chemin_valide(p) or p not in used for p in files):
        refuser('invalid_files')
    sizes = {}
    for f in files.values():
        if f['sha256'] in sizes and sizes[f['sha256']] != f['size']:
            refuser('invalid_files')
        sizes[f['sha256']] = f['size']
    if any(k in keys for k in m.get('removeVariants', [])):
        refuser('invalid_removals')
    context = context or {}
    if any(k not in keys and k not in m.get('removeVariants', [])
           for k in context.get('currentVariants', [])):
        refuser('variant_dropped')
    if context.get('episodeAudioUrl') and any(
            (v.get('audio') or {}).get('source') == 'publisher_stream'
            and v['audio']['url'] != context['episodeAudioUrl'] for v in variants):
        refuser('stream_mismatch')
    return m


def valider_segments(doc, variant, source_ids=None):
    schema('segments', doc)
    segments = doc['segments']
    if doc['variantKey'] != variant['key'] or len({s['id'] for s in segments}) != len(segments):
        refuser('invalid_segments')
    audio = variant.get('audio') or {}
    timed = bool(audio) and audio['timingSource'] != 'none'
    last_start, last_end = -1, -1
    for s in segments:
        start, end = s['startMs'], s['endMs']
        if timed:
            if (start is None or end is None or start <= last_start or end <= last_end
                    or end <= start or end > audio['durationMs']):
                refuser('invalid_timing')
            last_start, last_end = start, end
        elif start is not None or end is not None:
            refuser('invalid_timing')
        if variant.get('coverage', 'full') != 'full' and not s.get('sourceSegments'):
            refuser('missing_source_segments')
        if any(i not in (source_ids or set()) for i in s.get('sourceSegments', [])):
            refuser('invalid_source_segments')
    return doc
