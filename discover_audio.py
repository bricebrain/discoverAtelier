"""Pilotage de Kokoro, calibrage du débit et audio MP3 avec timings exacts."""
import json
from pathlib import Path

import pipeline
from discover_download import empreinte
from discover_evaluation import mots
from discover_source import commande, ffmpeg
from discover_ai import empreinte as fingerprint

BASE = Path(__file__).parent
VOICES = {'Narrator': 'bf_emma', 'Host': 'bf_emma', 'Guest': 'bm_george'}


def executer(segments, folder, name, verifier, speeds=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    inputs = [{**s, 'voice': VOICES[s['speaker']], 'speed': (speeds or {}).get(VOICES[s['speaker']], 1.0)} for s in segments]
    model_version = [[p.stat().st_size,p.stat().st_mtime_ns] for p in (BASE/'modeles_tts/kokoro-v1.0.onnx',BASE/'modeles_tts/voices-v1.0.bin')]
    signature = fingerprint([inputs,model_version])
    record = folder / (name + '.audio.json')
    cached = pipeline.lire_json(str(record))
    mp3, wav, timings = (folder / (name + suffix) for suffix in ('.mp3', '.wav', '.timings.json'))
    if (cached and cached.get('signature') == signature and mp3.exists() and timings.exists()
            and cached.get('sha256') == empreinte(mp3) and cached.get('timingsSha256') == empreinte(timings)):
        verifier()
        return cached
    input_path = folder / (name + '.tts.json')
    pipeline.ecrire_json(str(input_path), inputs)
    python = BASE / 'venv-tts/bin/python'
    if not python.exists():
        raise ValueError('L’environnement Kokoro venv-tts est absent.')
    commande([str(python), str(BASE / 'discover_tts_worker.py'), '--input', str(input_path), '--output', str(wav),
              '--timings', str(timings), '--cache', str(folder / 'tts-cache')], verifier)
    verifier()
    temporary = mp3.with_suffix('.part.mp3')
    try:
        commande([ffmpeg(), '-nostdin', '-y', '-v', 'error', '-i', str(wav), '-ac', '1', '-b:a', '64k', str(temporary)], verifier)
        temporary.replace(mp3)
    finally:
        temporary.unlink(missing_ok=True)
    duration = pipeline.duree_audio_secondes(str(mp3))
    if not duration:
        raise ValueError('Durée Kokoro illisible.')
    record_data = {'signature': signature, 'file': str(mp3), 'durationMs': round(duration * 1000),
                   'timingsFile': str(timings), 'timingsSha256': empreinte(timings), 'sha256': empreinte(mp3)}
    pipeline.ecrire_json(str(record), record_data)
    wav.unlink(missing_ok=True)
    return record_data


def calibrer(folder, verifier):
    folder = Path(folder)
    cache = folder / 'kokoro-calibration.json'
    version = [[p.stat().st_size, p.stat().st_mtime_ns] for p in
               [BASE / 'modeles_tts/kokoro-v1.0.onnx', BASE / 'modeles_tts/voices-v1.0.bin']]
    old = pipeline.lire_json(str(cache))
    if old and old.get('version') == version:
        return old['speeds']
    sample = ('A clear explanation helps us understand a difficult subject. We can listen to the main idea, then look at the evidence. '
              'Some people may agree with the first argument. Others may have a different view. Both views should be explained fairly. '
              'A useful example connects an abstract idea to everyday life. Facts and opinions are different, and we should keep that difference clear. '
              'When the evidence is uncertain, the explanation should say so. Good questions can help us notice what we know and what we still need to learn. '
              'Listening slowly gives us time to think about the words and their meaning.')
    speeds, rates = {}, {}
    for speaker in ['Narrator', 'Guest']:
        audio = executer([{'id': 'calibration', 'text': sample, 'speaker': speaker}], folder, 'calibrate-' + speaker.lower(), verifier)
        timings = json.loads(Path(audio['timingsFile']).read_text())
        rate = len(mots(sample)) / (timings[0]['endMs'] / 60_000)
        voice = VOICES[speaker]
        rates[voice] = round(rate, 2)
        speeds[voice] = round(min(1.4, max(.6, 130 / rate)), 3)
    pipeline.ecrire_json(str(cache), {'version': version, 'speeds': speeds, 'measuredWordsPerMinute': rates, 'targetWordsPerMinute': 130})
    return speeds
