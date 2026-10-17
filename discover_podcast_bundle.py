"""Manifeste podcast : original officiel, fidèle facultatif, adaptation ; conservation des autres variantes."""
import copy
import json
from pathlib import Path

import pipeline
from discover_download import empreinte
from discover_ai import empreinte as fingerprint
from manifeste_validation import valider_manifeste, valider_segments


def variant_key(options):
    suffix = options['level'].lower()
    key = f"en-{options['coverage']}-{suffix}"
    if options['targetMinutes']:
        key += f"-{options['targetMinutes']}m"
    if options['style'] == 'dialogue':
        key += '-d'
    return key


def construire(item, source, prepared, audio, folder, faithful=None, faithful_audio=None, previous=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    language = item['source']['language']
    original_key = language + '-source'
    options = item['options']
    paths, files, variants = {}, {}, []
    source_duration = pipeline.duree_audio_secondes(source['audioFile'])
    if not source_duration:
        raise ValueError('Durée originale illisible.')
    original_doc = json.loads(Path(source['segmentsFile']).read_text())
    ids = {s['id'] for s in original_doc['segments']}

    def add(path, local, content_type):
        local = Path(local)
        files[path] = {'sha256': empreinte(local), 'size': local.stat().st_size, 'contentType': content_type}
        paths[path] = str(local)

    def document(key, segments, variant, key_vocab=None):
        doc = {'schemaVersion': 1, 'variantKey': key, 'segments': segments}
        if key_vocab:
            doc['keyVocab'] = key_vocab
        local = folder / (key + '.json')
        pipeline.ecrire_json(str(local), doc)
        add('segments/' + key + '.json', local, 'application/json')
        variant['segmentsFile'] = 'segments/' + key + '.json'
        valider_segments(doc, variant, ids)
        variants.append(variant)

    timed = bool(original_doc.get('timingSource') != 'none')
    last_start, last_end = -1, -1
    for s in original_doc['segments']:
        a, b = s.get('startMs'), s.get('endMs')
        if a is None or b is None or a <= last_start or b <= last_end or b <= a or b > round(source_duration * 1000):
            timed = False
            break
        last_start, last_end = a, b
    if original_doc.get('timingSource') in ('rss_srt', 'rss_vtt') and original_doc['segments']:
        reference_end = original_doc['segments'][-1].get('endMs')
        if reference_end is None or abs(reference_end - source_duration*1000) > 1500:
            timed = False
    original_audio = {'source': 'publisher_stream', 'url': item['source']['audioUrl'], 'origin': 'original',
                      'durationMs': round(source_duration * 1000), 'timingSource': original_doc['timingSource'] if timed else 'none'}
    if options['keepOriginalCopy']:
        original_audio.pop('url')
        original_audio.update(source='r2', file='audio/' + original_key + '.mp3')
        add(original_audio['file'], source['audioFile'], 'audio/mpeg')
    original = [{k: s[k] for k in ('id', 'text', 'speaker') if s.get(k) is not None} |
                {'startMs': s.get('startMs') if timed else None, 'endMs': s.get('endMs') if timed else None}
                for s in original_doc['segments']]
    document(original_key, original, {'key': original_key, 'kind': 'source', 'language': language, 'coverage': 'full', 'audio': original_audio})

    def narrated(key, script, result, variant):
        timing = json.loads(Path(result['timingsFile']).read_text())
        if [t['id'] for t in timing] != [s['id'] for s in script]:
            raise ValueError('Timings Kokoro incompatibles avec les segments.')
        mapped = [{k: s[k] for k in ('id', 'text', 'fr', 'speaker', 'sourceSegments') if s.get(k) is not None} |
                  {'startMs': t['startMs'], 'endMs': t['endMs']} for s, t in zip(script, timing)]
        path = 'audio/' + key + '.mp3'
        add(path, result['file'], 'audio/mpeg')
        variant['audio'] = {'source': 'r2', 'file': path, 'origin': 'kokoro', 'durationMs': result['durationMs'], 'timingSource': 'kokoro'}
        document(key, mapped, variant, prepared['script'].get('keyVocab') if variant['kind'] == 'adaptation' else None)

    if faithful:
        narrated('en-faithful', faithful, faithful_audio, {'key': 'en-faithful', 'kind': 'faithful_translation',
                  'language': 'en', 'coverage': 'full', 'derivedFrom': original_key})
    key = variant_key(options)
    adaptation = {'key': key, 'kind': 'adaptation', 'language': 'en', 'cefrLevel': None if options['level'] == 'original' else options['level'],
                  'style': options['style'], 'coverage': options['coverage'], 'derivedFrom': original_key,
                  'generation': prepared['generation'], 'evaluation': prepared['evaluation']}
    if options['coverage'] != 'full':
        adaptation['condensation'] = {'targetMinutes': options['targetMinutes'], 'sourceMinutes': source_duration / 60, 'excludeAds': True}
    narrated(key, prepared['script']['segments'], audio, adaptation)
    if previous:
        old_source = next(v for v in previous['variants'] if v['kind'] == 'source')
        # Une réinterprétation des mêmes IDs casserait les renvois des anciennes variantes.
        if previous['files'][old_source['segmentsFile']]['sha256'] != files[variants[0]['segmentsFile']]['sha256']:
            raise ValueError('La source publiée a changé. Conserver et vérifier la source avant de préparer une autre version.')
        if old_source.get('audio', {}).get('source') == 'r2' and not options['keepOriginalCopy']:
            variants[0]['audio'] = copy.deepcopy(old_source['audio'])
            old_path = old_source['audio']['file']
            files[old_path] = previous['files'][old_path]
        keys = {v['key'] for v in variants}
        for variant in previous['variants']:
            if variant['key'] not in keys:
                variants.append(copy.deepcopy(variant))
                for path in [variant['segmentsFile'], (variant.get('audio') or {}).get('file')]:
                    if path:
                        files[path] = previous['files'][path]
    manifest = {'schemaVersion': 1, 'content': {'id': 'podcast-' + item['ref'], 'title': item['source']['title'],
                'originalLanguage': language, 'sourceType': 'podcast', 'sourceRef': 'episode:' + item['ref'],
                'sourceUrl': item['source']['audioUrl'], 'category': item['source']['category'], 'rights': 'personal_use',
                'editorial': 'discovery' if item['source']['category'] in ('stories', 'science') else 'news'},
                'variants': variants, 'files': files, 'removeVariants': []}
    valider_manifeste(manifest, {'episodeAudioUrl': item['source']['audioUrl']})
    pipeline.ecrire_json(str(folder / 'manifest.json'), manifest)
    return manifest, paths
