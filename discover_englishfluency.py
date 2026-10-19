"""Pont facultatif après publication Discover ; reprise locale sans génération."""
import argparse
import fcntl
import http.client
import json
import threading
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import pipeline
from discover_ai import empreinte
from discover_download import empreinte as empreinte_fichier

VERROU = threading.RLock()
MAX_AUDIO = 100 * 1024 * 1024  # contrat Worker EnglishFluency


def destination(config):
    settings = config.get('englishFluency') or {}
    url = urlsplit(settings.get('workerUrl', ''))
    secret = settings.get('apiSecret', '')
    local = url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1')
    if (not url.hostname or (url.scheme != 'https' and not local) or url.username or url.password
            or url.query or url.fragment or url.path not in ('', '/')
            or not isinstance(secret, str) or not secret or '\r' in secret or '\n' in secret):
        raise ValueError('Configuration EnglishFluency invalide.')
    profile = settings.get('profileId', 'default')
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError('Profil EnglishFluency invalide.')
    return {'workerUrl': settings['workerUrl'].rstrip('/'), 'apiSecret': secret, 'profileId': profile}


def requete(config, path, data=None, fichier=None):
    """Transport injectable, sans redirection ni corps d'erreur distant dans les journaux."""
    url = urlsplit(config['workerUrl'])
    cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    connection = cls(url.hostname, url.port, timeout=120)
    headers = {'Authorization': 'Bearer ' + config['apiSecret'], 'User-Agent': 'Mozilla/5.0 discover-atelier/1.0'}
    try:
        if fichier:
            headers.update({'Content-Type': 'audio/mpeg', 'Content-Length': str(Path(fichier).stat().st_size)})
            with open(fichier, 'rb') as stream:
                connection.request('POST', path, body=stream, headers=headers)
        else:
            headers['Content-Type'] = 'application/json'
            connection.request('POST', path, body=json.dumps(data, ensure_ascii=False).encode('utf-8'), headers=headers)
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            raise RuntimeError('EnglishFluency : HTTP ' + str(response.status))
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise RuntimeError('Réponse EnglishFluency trop volumineuse.')
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise RuntimeError('Réponse EnglishFluency invalide.')
        return result
    finally:
        connection.close()


def construire(manifest, paths, key, profile):
    """Une adaptation EN courante devient un podcast bilingue v2 indépendant."""
    content = manifest['content']
    variant = next(v for v in manifest['variants'] if v['key'] == key)
    if variant['language'] != 'en' or variant['kind'] != 'adaptation':
        raise ValueError('Le pont attend une adaptation anglaise.')
    segment_path = Path(paths[variant['segmentsFile']])
    if empreinte_fichier(segment_path) != manifest['files'][variant['segmentsFile']]['sha256']:
        raise ValueError('Texte local différent de la publication Discover.')
    document = json.loads(segment_path.read_text(encoding='utf-8'))
    audio = variant.get('audio') or {}
    audio_path = paths.get(audio.get('file'))
    if audio and (audio.get('source') != 'r2' or not audio_path):
        raise ValueError('Audio local anglais manquant.')
    audio_hash = None
    if audio_path:
        audio_path = str(Path(audio_path).resolve())
        size = Path(audio_path).stat().st_size
        audio_hash = empreinte_fichier(audio_path)
        expected = manifest['files'][audio['file']]
        if not 0 < size <= MAX_AUDIO or size != expected['size'] or audio_hash != expected['sha256']:
            raise ValueError('Audio anglais invalide ou modifié.')
    # IDs globaux côté Worker : inclure le profil et la variante, jamais la révision.
    remote_id = 'discover-' + empreinte([profile, content['id'], key])[:40]
    segments = []
    for s in document['segments']:
        if not s.get('text') or not s.get('fr'):
            raise ValueError('Paragraphes bilingues requis.')
        segments.append({'id': s['id'], 'en': s['text'], 'fr': s['fr'],
                         'startMs': s.get('startMs') if audio_path else None,
                         'endMs': s.get('endMs') if audio_path else None})
    if not segments:
        raise ValueError('Adaptation vide.')
    timed = bool(audio_path) and audio.get('timingSource') in ('kokoro', 'deepgram') and all(
        isinstance(s['startMs'], (int, float)) and isinstance(s['endMs'], (int, float))
        and 0 <= s['startMs'] < s['endMs'] <= audio['durationMs'] for s in segments)
    if not timed:
        for s in segments:
            s.update(startMs=None, endMs=None)
    text_en = '\n\n'.join(s['en'] for s in segments)
    text_fr = '\n\n'.join(s['fr'] for s in segments)
    metadata = {
        'schemaVersion': 2, 'sourceType': content['sourceType'], 'sourceUrl': content.get('sourceUrl'),
        'sourceLanguage': content['originalLanguage'], 'learningLanguage': 'en', 'language': 'en',
        'audioLanguage': 'en' if audio_path else None, 'transcriptLanguage': 'en',
        'transcriptText': text_en, 'textEn': text_en, 'textFr': text_fr, 'segments': segments,
        'variantId': content['id'] + ':' + key, 'variantKind': 'adaptation',
        'audioOrigin': ('kokoro_tts' if audio.get('origin') == 'kokoro' else audio.get('origin')) if audio_path else None,
        'audioRevision': audio_hash, 'timingSource': audio.get('timingSource') if timed else 'none',
        'timingStatus': 'valid' if timed else 'unavailable', 'readingAvailable': True, 'listeningAvailable': timed,
        'keyVocab': list(dict.fromkeys(document.get('keyVocab') or [])), 'chunks': [], 'grammarPoints': [],
        'discoverContentId': content['id'], 'discoverVariantKey': key,
        'durationSeconds': audio.get('durationMs', 0) / 1000 if audio_path else None,
        'durationLabel': f"{max(1, round(audio['durationMs'] / 60_000))} min" if audio_path else 'Texte',
    }
    payload = {'id': remote_id, 'profileId': profile, 'type': 'podcast', 'title': content['title'],
               'level': variant.get('cefrLevel'), 'topic': content.get('category'), 'body': text_en,
               'audioR2Key': f'prepared-content/{remote_id}-{audio_hash}.mp3' if audio_path else None,
               'metadata': metadata}
    metadata['contentRevision'] = empreinte(payload)
    return {'payload': payload, 'audioPath': audio_path}


def _lire(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _envoyer(folder, packet, target, transport):
    payload = packet['payload']
    fingerprint = empreinte([target['workerUrl'], payload])
    state_path = folder / 'englishfluency-state.json'
    state = _lire(state_path) if state_path.exists() else {}
    if state.get('fingerprint') == fingerprint and state.get('status') == 'published':
        return state
    state = {'fingerprint': fingerprint, 'remoteId': payload['id'], 'status': 'pending'}
    pipeline.ecrire_json(str(state_path), state)
    try:
        if packet['audioPath']:
            audio = Path(packet['audioPath'])
            if empreinte_fichier(audio) != payload['metadata']['audioRevision']:
                raise ValueError('Audio local modifié : reprise refusée.')
            # Réenvoyer la même clé est idempotent et répare un pending expiré (24 h).
            result = transport(target, '/content/audio?' + urlencode({'key': payload['audioR2Key'], 'contentId': payload['id']}),
                               fichier=str(audio))
            if result.get('ok') is not True or result.get('key') != payload['audioR2Key']:
                raise RuntimeError('Accusé audio EnglishFluency invalide.')
            state['status'] = 'audio_uploaded'
            pipeline.ecrire_json(str(state_path), state)
        if transport(target, '/content', data=payload).get('ok') is not True:
            raise RuntimeError('Accusé contenu EnglishFluency invalide.')
        state['status'] = 'published'
    except Exception:
        # Une erreur du transport peut contenir le secret : ne jamais la persister.
        state.update(status='failed', error='Envoi EnglishFluency interrompu ; reprise locale possible.')
    pipeline.ecrire_json(str(state_path), state)
    return state


def _executer(folder, config, transport, creer=None):
    if (config.get('englishFluency') or {}).get('enabled') is not True:
        return {'status': 'disabled'}
    folder = Path(folder)
    target = destination(config)
    with VERROU, (folder / 'englishfluency.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _lire(folder / 'published.json').get('status') != 'ready':
            raise ValueError('Discover doit être publié avant EnglishFluency.')
        packet_path = folder / 'englishfluency-packet.json'
        if creer:
            packet = creer(target['profileId'])
            packet['destination'] = {k: target[k] for k in ('workerUrl', 'profileId')}
            pipeline.ecrire_json(str(packet_path), packet)
        else:
            packet = _lire(packet_path)
            if packet['destination'] != {k: target[k] for k in ('workerUrl', 'profileId')}:
                raise ValueError('Destination différente : relancer depuis la préparation.')
        return _envoyer(folder, packet, target, transport or requete)


def publier(manifest, paths, key, folder, config, transport=None):
    return _executer(folder, config, transport, lambda profile: construire(manifest, paths, key, profile))


def reprendre(folder, config, transport=None):
    """Reprend uniquement le pont : aucun appel Discover, IA ou TTS."""
    return _executer(folder, config, transport)


def main():
    parser = argparse.ArgumentParser(description='Reprendre « aussi vers EnglishFluency » après publication Discover.')
    parser.add_argument('folder', help='Dossier prepared-* contenant englishfluency-packet.json')
    parser.add_argument('--config', default=str(Path(__file__).with_name('config_discover.json')))
    args = parser.parse_args()
    try:
        state = reprendre(args.folder, _lire(args.config))
        print('EnglishFluency : ' + state['status'])
        return 0 if state['status'] == 'published' else 1
    except Exception:
        print('Reprise impossible : vérifier configuration, paquet local et publication Discover.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
