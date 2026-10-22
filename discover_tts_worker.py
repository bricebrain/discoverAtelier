#!/usr/bin/env python3
"""Kokoro local : cache par segment, voix stables et assemblage WAV en flux."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro
from tts_kokoro import CHEMIN_MODELE, CHEMIN_VOIX, TAUX, SILENCE_ENTRE_BLOCS, SILENCE_ENTRE_SEGMENTS, decouper_texte


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--timings', required=True)
    parser.add_argument('--cache', required=True)
    args = parser.parse_args()
    segments = json.loads(Path(args.input).read_text())
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    model_version = [(Path(p).stat().st_size, Path(p).stat().st_mtime_ns) for p in (CHEMIN_MODELE, CHEMIN_VOIX)]
    kokoro = None
    output = Path(args.output)
    temporary = output.with_suffix('.part.wav')
    timings, cursor = [], 0
    try:
        with sf.SoundFile(temporary, 'w', samplerate=TAUX, channels=1, subtype='PCM_16', format='WAV') as writer:
            for i, segment in enumerate(segments):
                voice, speed = segment['voice'], segment['speed']
                key = hashlib.sha256(json.dumps([segment['text'], voice, speed, model_version, SILENCE_ENTRE_BLOCS]).encode()).hexdigest()
                path = cache / (key + '.wav')
                try:
                    valid = path.exists() and sf.info(path).frames > 0
                except (OSError, RuntimeError):
                    valid = False
                if not valid:
                    if kokoro is None:
                        kokoro = Kokoro(CHEMIN_MODELE, CHEMIN_VOIX)
                    part = path.with_suffix('.part.wav')
                    try:
                        with sf.SoundFile(part, 'w', samplerate=TAUX, channels=1, subtype='PCM_16', format='WAV') as out:
                            for j, text in enumerate(decouper_texte(segment['text'])):
                                if j:
                                    out.write(np.zeros(int(TAUX * SILENCE_ENTRE_BLOCS)))
                                audio, rate = kokoro.create(text, voice=voice, speed=speed,
                                                            lang='en-gb' if voice.startswith('b') else 'en-us')
                                if rate != TAUX or len(audio) == 0:
                                    raise RuntimeError('Sortie Kokoro invalide.')
                                out.write(audio)
                        part.replace(path)
                    finally:
                        part.unlink(missing_ok=True)
                start = cursor
                with sf.SoundFile(path) as audio:
                    for block in audio.blocks(blocksize=65536):
                        writer.write(block)
                        cursor += len(block)
                timings.append({'id': segment['id'], 'startMs': round(start / TAUX * 1000), 'endMs': round(cursor / TAUX * 1000)})
                silence = int(TAUX * SILENCE_ENTRE_SEGMENTS)
                writer.write(np.zeros(silence))
                cursor += silence
                print(f'PROGRESSION {i + 1}/{len(segments)}', flush=True)
        temporary.replace(output)
        Path(args.timings).write_text(json.dumps(timings))
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
