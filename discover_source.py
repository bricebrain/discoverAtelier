"""Point de reprise source : audio mono 64 kbit/s, transcription RSS ou MacWhisper et segments."""
import html
import json
import re
import shutil
import subprocess
import time
import tempfile
from pathlib import Path

import horodatage
import pipeline
from discover_download import empreinte, telecharger


class IntervenantsIndisponibles(RuntimeError):
    pass


def commande(args, verifier, limite=7200):
    # Pas de capture illimitée des sorties ffmpeg/MacWhisper ni de processus abandonné après perte de bail.
    with tempfile.TemporaryFile() as journal, subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=journal) as process:
        debut = time.monotonic()
        try:
            while process.poll() is None:
                verifier()
                if time.monotonic() - debut > limite:
                    raise RuntimeError('Traitement audio trop long.')
                time.sleep(0.25)
            verifier()
            if process.returncode:
                journal.seek(0, 2)
                journal.seek(max(0, journal.tell() - 4000))
                if b'does not support speaker detection' in journal.read(4000):
                    raise IntervenantsIndisponibles('Le modèle MacWhisper ne détecte pas les intervenants.')
                raise RuntimeError('Le traitement audio a échoué. Vérifier ffmpeg ou MacWhisper.')
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise


def repliques(texte):
    texte = texte.replace('\r\n', '\n')
    # Le parseur SRT accepte les cues VTT après normalisation des timestamps et suppression des balises.
    texte = re.sub(r'(?m)^(\d{2}:\d{2}\.\d{3})', r'00:\1', texte)
    texte = re.sub(r'(--\> )(\d{2}:\d{2}\.\d{3})', r'\g<1>00:\2', texte)
    texte = re.sub(r'(<[^>]*>)', '', texte)
    return horodatage.lire_srt(html.unescape(texte))


def ffmpeg():
    executable = shutil.which('ffmpeg')
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:
        raise RuntimeError('ffmpeg est nécessaire à la préparation audio.') from e


def preparer(item, dossier, etape, verifier):
    source = item['source']
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    cache = dossier / 'source.json'
    precedent = pipeline.lire_json(str(cache)) or {}
    original = dossier / 'download.audio'
    normalise = dossier / 'source.mp3'
    meme_source = precedent.get('audioUrl') == source['audioUrl']
    etape('download')
    if not (meme_source and original.is_file() and precedent.get('downloadSha256') == empreinte(original)):
        sha = telecharger(source['audioUrl'], original, 250_000_000, verifier)
        precedent = {'audioUrl': source['audioUrl'], 'downloadSha256': sha}
        pipeline.ecrire_json(str(cache), precedent)
    verifier()
    etape('normalize')
    if not (normalise.is_file() and precedent.get('audioSha256') == empreinte(normalise)):
        temporaire = dossier / 'source.part.mp3'
        try:
            commande([ffmpeg(), '-nostdin', '-y', '-v', 'error', '-i', str(original), '-vn',
                      '-ac', '1', '-ar', '24000', '-b:a', '64k', str(temporaire)], verifier)
            temporaire.replace(normalise)
        finally:
            temporaire.unlink(missing_ok=True)
        precedent['audioSha256'] = empreinte(normalise)
        pipeline.ecrire_json(str(cache), precedent)
    etape('transcribe')
    segments_path = dossier / 'segments-source.json'
    # Une transcription n'est réutilisée que pour exactement le même audio et les mêmes métadonnées de flux.
    transcription_key = [precedent['audioSha256'], source.get('transcriptUrl'), source.get('language')]
    if (precedent.get('transcriptionKey') == transcription_key and segments_path.is_file()
            and precedent.get('segmentsSha256') == empreinte(segments_path)):
        verifier()
        precedent.update({'source': source, 'options': item['options']})
        pipeline.ecrire_json(str(cache), precedent)
        return precedent
    texte = None
    timing = 'none'
    speakers_detected = None
    if source.get('transcriptUrl') and source.get('transcriptType') in ('srt', 'vtt'):
        chemin = dossier / ('transcript.' + source['transcriptType'])
        try:
            telecharger(source['transcriptUrl'], chemin, 5_000_000, verifier)
            texte = chemin.read_text(encoding='utf-8-sig')
            cues = repliques(texte)
            if not cues:
                raise ValueError('Transcription du flux illisible.')
            timing = 'rss_' + source['transcriptType']
        except (OSError, ValueError, RuntimeError):
            verifier()
            texte = None
    if texte is None:
        import transcription
        mw = transcription.trouver_macwhisper()
        if not mw:
            raise RuntimeError('MacWhisper est nécessaire : ce flux ne fournit pas de transcription lisible.')
        srt = dossier / 'macwhisper.srt'
        with transcription.VERRO_WHISPER:
            verifier()
            args = [mw, 'transcribe', '--language', source['language'], '--format', 'srt',
                    '--output', str(srt), '--speakers', '--overwrite', str(normalise)]
            try:
                commande(args, verifier)
                speakers_detected = True
            except IntervenantsIndisponibles:
                verifier()
                args[args.index('--speakers')] = '--no-speakers'
                commande(args, verifier)
                speakers_detected = False
        cues = repliques(srt.read_text(encoding='utf-8-sig'))
        timing = 'macwhisper_srt'
    if not cues:
        raise RuntimeError('La transcription ne contient aucun segment lisible.')
    verifier()
    segments = [{'id': f's{i:04d}', 'text': c['text'], 'startMs': c['startMs'], 'endMs': c['endMs']}
                for i, c in enumerate(horodatage.regrouper_repliques(cues), 1)]
    pipeline.ecrire_json(str(segments_path), {'language': source['language'], 'timingSource': timing, 'segments': segments})
    precedent.update({'transcriptionKey': transcription_key, 'segmentsSha256': empreinte(segments_path),
                      'audioFile': str(normalise), 'segmentsFile': str(segments_path),
                      'source': source, 'options': item['options'], 'timingSource': timing,
                      'speakersDetected': speakers_detected})
    pipeline.ecrire_json(str(cache), precedent)
    verifier()
    return precedent
