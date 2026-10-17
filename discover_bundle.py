"""Mapper des bundles YouTube bilingues vers le contrat Discover."""
import hashlib
import json
from pathlib import Path

import bundles
import pipeline
from manifeste_validation import valider_manifeste, valider_segments


def empreinte(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def construire(slug):
    meta = bundles.lire_meta(slug)
    if not meta or meta.get('sourceType') != 'youtube':
        raise ValueError('La cible Discover du lot 6 accepte les bundles YouTube.')
    source = pipeline.langue_source(meta)
    segments = pipeline.lire_segments(slug)
    if source not in ('fr', 'en') or not segments or not pipeline.traduction_complete(segments):
        raise ValueError('Source et traduction fidèle complètes requises.')
    # Les traductions existantes restent fidèles : leur niveau cible n’en fait pas une adaptation.
    variants, files, paths = [], {}, {}
    folder = Path(bundles.DOSSIER_BUNDLES) / '.discover' / slug
    folder.mkdir(parents=True, exist_ok=True)

    def add_file(relative, local, content_type):
        local = Path(local)
        files[relative] = {'sha256': empreinte(local), 'size': local.stat().st_size,
                           'contentType': content_type}
        paths[relative] = str(local)

    for language in [source, 'en' if source == 'fr' else 'fr']:
        original = language == source
        key = language + ('-source' if original else '-faithful')
        variant = {'key': key, 'kind': 'source' if original else 'faithful_translation',
                   'language': language, 'cefrLevel': None, 'derivedFrom': None if original else source + '-source',
                   'coverage': 'full', 'segmentsFile': f'segments/{key}.json'}
        filename = f'{slug}.mp3' if original else f'{slug}.audio-en.mp3' if language == 'en' else None
        audio_path = Path(bundles.DOSSIER_BUNDLES) / filename if filename else None
        timing = None
        if audio_path and audio_path.is_file():
            if not original and pipeline.etat_publication(slug).get('audioEnObsolete'):
                raise ValueError('Régénérer l’audio Kokoro devenu obsolète.')
            duration = pipeline.duree_audio_secondes(str(audio_path))
            if not duration:
                raise ValueError('Durée audio illisible ; vérifier ffmpeg.')
            # Les timestamps des segments locaux sont ceux de la source MacWhisper.
            if original and pipeline.lire_infos_segments(slug).get('timingSource') == 'macwhisper_srt':
                timing = [{'startMs': s.get('startMs'), 'endMs': s.get('endMs')} for s in segments]
            elif not original:
                timing = pipeline.lire_timings_kokoro(slug, segments)
            variant['audio'] = {'source': 'r2', 'file': f'audio/{key}.mp3',
                                'origin': 'original' if original else 'kokoro',
                                'durationMs': round(duration * 1000),
                                'timingSource': ('macwhisper_srt' if original else 'kokoro') if timing else 'none'}
            add_file(variant['audio']['file'], audio_path, 'audio/mpeg')
        mapped = []
        for i, s in enumerate(segments):
            t = timing[i] if timing else {}
            mapped.append({'id': s['id'], 'text': s[language],
                           **({'fr': s['fr']} if language == 'en' and s.get('fr') else {}),
                           'startMs': t.get('startMs'), 'endMs': t.get('endMs')})
        doc = {'schemaVersion': 1, 'variantKey': key, 'segments': mapped}
        try:
            valider_segments(doc, variant)
        except ValueError:
            # Horodatage ancien incohérent : texte et audio restent publiables sans surlignage.
            if variant.get('audio'):
                variant['audio']['timingSource'] = 'none'
            for s in mapped:
                s['startMs'] = s['endMs'] = None
            valider_segments(doc, variant)
        local = folder / f'{key}.json'
        local.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':')), encoding='utf-8')
        add_file(variant['segmentsFile'], local, 'application/json')
        variants.append(variant)
    manifest = {'schemaVersion': 1, 'content': {
        'id': slug, 'title': meta['title'], 'originalLanguage': source, 'sourceType': 'youtube',
        'sourceUrl': meta.get('sourceUrl'), 'editorial': 'discovery', 'rights': 'personal_use'},
        'variants': variants, 'files': files, 'removeVariants': []}
    valider_manifeste(manifest)
    return manifest, paths
