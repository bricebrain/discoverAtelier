"""Aura-2 : fragments en cache, un seul essai HTTP et WAV normalisé pour des timings exacts."""
import concurrent.futures
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import pipeline
from discover_tts_budget import Budget

RATE = 24000
MAX_CHARACTERS = 1800
MAX_AUDIO_BYTES = 12_000_000
INTRO_PAUSE_SECONDS = .3
PARAGRAPH_PAUSE_SECONDS = .6
# Fragments envoyés en même temps ; le coût est identique, seule l'attente diminue.
PARALLEL_FRAGMENTS = 4


class DeepgramIndisponible(RuntimeError):
    pass


def characters(text):
    # Comptage UTF-16 conservateur, y compris espaces et ponctuation.
    return len(text.encode('utf-16-le')) // 2


def chunks(text):
    text = text.strip()
    parts = []
    while text:
        end = min(len(text), MAX_CHARACTERS)
        while characters(text[:end]) > MAX_CHARACTERS:
            end -= 1
        if end < len(text):
            sentences = [m.end() for m in re.finditer(r'[.!?][\"”’]?\s+', text[:end])]
            end = sentences[-1] if sentences and sentences[-1] > end // 2 else max(
                (m.end() for m in re.finditer(r'\s+', text[:end])), default=end)
        piece, text = text[:end].strip(), text[end:].lstrip()
        if piece:
            parts.append(piece)
    return parts


def fragment_key(text, voice, speed):
    raw = json.dumps(['aura-2-wav-v1', text, voice, speed, RATE], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def pcm(raw):
    try:
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, RATE, 'NONE'):
                raise ValueError('Format audio inattendu.')
            data = audio.readframes(MAX_AUDIO_BYTES // 2 + 1)
        if not data or len(data) % 2 or len(data) > MAX_AUDIO_BYTES:
            raise ValueError('Audio vide ou trop volumineux.')
        return data
    except (wave.Error, EOFError, ValueError) as error:
        raise DeepgramIndisponible('Réponse audio Deepgram invalide.') from error


def cache_path(root, key):
    return Path(root) / 'cache' / (key + '.wav')


def cached(root, key):
    path = cache_path(root, key)
    info = pipeline.lire_json(str(path.with_suffix('.json')))
    if not info or not path.exists() or path.stat().st_size > MAX_AUDIO_BYTES:
        return False
    try:
        raw = path.read_bytes()
        return hashlib.sha256(raw).hexdigest() == info.get('sha256') and bool(pcm(raw))
    except (OSError, DeepgramIndisponible):
        return False


def voice_for(segment, voice):
    # L'invité du dialogue prend une voix contrastée (une voix féminine face à Arcas).
    guest = {'draco': 'cora', 'arcas': 'thalia'}.get(voice, 'draco')
    return guest if segment.get('speaker') == 'Guest' else voice


def plan(segments, root, voice, speed):
    result = []
    for segment in segments:
        for text in chunks(segment['text']):
            key = fragment_key(text, voice_for(segment, voice), speed)
            result.append({'text': text, 'key': key, 'characters': characters(text), 'cached': cached(root, key)})
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeepgramIndisponible('Redirection Deepgram refusée.')


def request(text, model, speed, api_key, opener=None):
    params = urllib.parse.urlencode({'model': model, 'speed': speed, 'encoding': 'linear16', 'container': 'wav', 'sample_rate': RATE})
    req = urllib.request.Request('https://api.deepgram.com/v1/speak?' + params,
        data=json.dumps({'text': text}).encode(), headers={'Authorization': 'Token ' + api_key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with (opener or urllib.request.build_opener(NoRedirect()).open)(req, timeout=90) as response:
            raw = response.read(MAX_AUDIO_BYTES + 1)
            if len(raw) > MAX_AUDIO_BYTES or not response.headers.get('Content-Type', '').startswith('audio/'):
                raise DeepgramIndisponible('Réponse audio Deepgram invalide.')
            return pcm(raw)
    except urllib.error.HTTPError as error:
        # Code seul : ni corps de réponse ni clé API dans le message.
        raise DeepgramIndisponible(f'Deepgram a refusé le fragment (HTTP {error.code}) ; appel conservé dans le budget par prudence.') from error
    except TimeoutError as error:
        raise DeepgramIndisponible('Deepgram : délai de réponse dépassé ; appel conservé dans le budget par prudence.') from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # Pas de corps ni de clé API dans les erreurs ; aucune relance HTTP automatique.
        raise DeepgramIndisponible('Deepgram indisponible ; appel conservé dans le budget par prudence.') from error


def fragment(text, root, config, verifier, transport=None):
    voice, speed = config['tts']['voice'], config['tts']['speed']
    key = fragment_key(text, voice, speed)
    path = cache_path(root, key)
    if cached(root, key):
        return path
    verifier()
    budget = Budget(root)
    budget.reserve(key, characters(text), config['tts']['monthlyLimitUsd'])
    try:
        data = (transport or request)(text, 'aura-2-' + voice + '-en', speed, config['deepgramApiKey'])
        if not data or len(data) % 2 or len(data) > MAX_AUDIO_BYTES:
            raise DeepgramIndisponible('Réponse audio Deepgram invalide.')
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.part.wav')
        try:
            with wave.open(str(temp), 'wb') as audio:
                audio.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
                audio.writeframes(data)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
        pipeline.ecrire_json(str(path.with_suffix('.json')), {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        budget.finish(key, True)
        return path
    except BaseException:
        budget.finish(key, False)
        raise


def part_config(segment, config):
    return {**config, 'tts': {**config['tts'], 'voice': voice_for(segment, config['tts']['voice'])}}


def prefetch(segments, root, config, verifier, transport=None):
    """Remplit le cache en parallèle ; au premier échec, aucun fragment non commencé n'est envoyé."""
    pending = {}
    for segment in segments:
        options = part_config(segment, config)
        for text in chunks(segment['text']):
            key = fragment_key(text, options['tts']['voice'], options['tts']['speed'])
            if key not in pending and not cached(root, key):
                pending[key] = (text, options)  # un texte répété n'est envoyé qu'une fois
    if len(pending) < 2:
        return
    failed = []

    def guarded():
        if failed:
            raise RuntimeError('Préparation audio interrompue.')
        verifier()

    def run(text, options):
        try:
            return fragment(text, root, options, guarded, transport)
        except BaseException as error:
            failed.append(error)
            raise

    with concurrent.futures.ThreadPoolExecutor(PARALLEL_FRAGMENTS) as pool:
        futures = [pool.submit(run, *job) for job in pending.values()]
        for future in concurrent.futures.as_completed(futures):
            if future.exception():
                for other in futures:
                    other.cancel()
                break
    if failed:
        raise failed[0]


def assemble(segments, root, config, output, timings_path, verifier, transport=None):
    output = Path(output)
    temporary = output.with_suffix('.part.wav')
    cursor, timings = 0, []
    started = time.monotonic()
    prefetch(segments, root, config, verifier, transport)
    try:
        with wave.open(str(temporary), 'wb') as writer:
            writer.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
            intro = round(RATE * INTRO_PAUSE_SECONDS)
            writer.writeframesraw(b'\0' * (intro * 2))
            cursor += intro
            for index, segment in enumerate(segments):
                verifier()
                if index:
                    silence = round(RATE * PARAGRAPH_PAUSE_SECONDS)
                    writer.writeframesraw(b'\0' * (silence * 2))
                    cursor += silence
                start = cursor
                for text in chunks(segment['text']):
                    path = fragment(text, root, part_config(segment, config), verifier, transport)
                    with wave.open(str(path), 'rb') as audio:
                        data = audio.readframes(audio.getnframes())
                    writer.writeframesraw(data)
                    cursor += len(data) // 2
                timings.append({'id': segment['id'], 'startMs': round(start / RATE * 1000), 'endMs': round(cursor / RATE * 1000)})
        verifier()
        temporary.replace(output)
        pipeline.ecrire_json(str(timings_path), timings)
        return {'durationMs': round(cursor / RATE * 1000), 'generationSeconds': round(time.monotonic() - started, 3)}
    finally:
        temporary.unlink(missing_ok=True)
