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


# ── Autres sources : vidéo YouTube et texte (note My Mind ou texte importé) ─────────────────────────

MOTS_FR = set('le la les des est et une un que pour pas dans du au aux ce cette qui sur avec sont nous vous ils elle mais ou'.split())
MOTS_EN = set('the and is of to in that it for not with are this was on be as at by have from but they you we'.split())


def detecter_langue(texte):
    """Français ou anglais d'après les mots outils (suffisant pour choisir la traduction fidèle)."""
    mots = re.findall(r"[a-zàâçéèêëîïôûùüÿœ']+", texte.lower())[:3000]
    fr = sum(m in MOTS_FR for m in mots)
    en = sum(m in MOTS_EN for m in mots)
    return 'en' if en > fr else 'fr'


def decouper_texte(texte, cible=220):
    """Segments d'environ 220 caractères, sans couper une phrase ; un paragraphe n'est jamais fusionné au suivant."""
    segments = []
    for paragraphe in re.split(r'\n\s*\n', texte.replace('\r\n', '\n')):
        lignes = ' '.join(l.strip().lstrip('#').strip() for l in paragraphe.split('\n') if l.strip())
        if not lignes:
            continue
        phrases = re.split(r'(?<=[.!?…])\s+', lignes)
        courant = ''
        for phrase in phrases:
            if courant and len(courant) + len(phrase) > cible:
                segments.append(courant)
                courant = phrase
            else:
                courant = (courant + ' ' + phrase).strip()
        if courant:
            segments.append(courant)
    return segments


def _transcrire_macwhisper(audio, dossier, langue, verifier):
    import transcription
    mw = transcription.trouver_macwhisper()
    if not mw:
        raise RuntimeError('MacWhisper est nécessaire pour transcrire cette source.')
    srt = Path(dossier) / 'macwhisper.srt'
    with transcription.VERRO_WHISPER:
        verifier()
        args = [mw, 'transcribe', '--language', langue or 'auto', '--format', 'srt',
                '--output', str(srt), '--speakers', '--overwrite', str(audio)]
        try:
            commande(args, verifier)
        except IntervenantsIndisponibles:
            verifier()
            args[args.index('--speakers')] = '--no-speakers'
            commande(args, verifier)
    return repliques(srt.read_text(encoding='utf-8-sig'))


def preparer_youtube(item, dossier, etape, verifier):
    import transcription
    import yt_dlp
    source = dict(item['source'])
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    cache = dossier / 'source.json'
    precedent = pipeline.lire_json(str(cache)) or {}
    etape('download')
    with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'noprogress': True, 'noplaylist': True}) as ydl:
        info = ydl.extract_info(source['url'], download=False) or {}
    source['title'] = (info.get('title') or source['title'])[:300]
    langue = (info.get('language') or '')[:2]
    source['language'] = langue if langue in ('fr', 'en') else None
    original = dossier / 'download.mp3'
    if not (original.is_file() and precedent.get('videoId') == source['videoId'] and precedent.get('downloadSha256') == empreinte(original)):
        options = {'format': 'bestaudio/best', 'noplaylist': True, 'outtmpl': str(dossier / 'download.%(ext)s'),
                   'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '128'}],
                   'ffmpeg_location': ffmpeg(), 'quiet': True, 'no_warnings': True, 'noprogress': True}
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([source['url']])
        if not original.is_file():
            raise RuntimeError('YouTube n’a pas fourni l’audio de cette vidéo (mettre yt-dlp à jour ?).')
        precedent = {'videoId': source['videoId'], 'downloadSha256': empreinte(original)}
        pipeline.ecrire_json(str(cache), precedent)
    verifier()
    etape('normalize')
    normalise = dossier / 'source.mp3'
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
    if precedent.get('transcriptionKey') == precedent['audioSha256'] and segments_path.is_file() \
            and precedent.get('segmentsSha256') == empreinte(segments_path):
        precedent.update({'source': {**source, **precedent.get('source', {})}, 'options': item['options']})
        return precedent
    cues, timing = None, 'macwhisper_srt'
    # Sous-titres manuels seulement : les automatiques se chevauchent et seraient moins fiables que MacWhisper.
    try:
        langue_st, automatiques = transcription.choisir_sous_titres(source['url'], [source['language']] if source['language'] else None)
        if langue_st and automatiques is False and langue_st[:2] in ('fr', 'en'):
            chemin = transcription.telecharger_sous_titres(source['url'], str(dossier / 'subtitles'), langue_st, False)
            if chemin:
                cues = repliques(Path(chemin).read_text(encoding='utf-8-sig')) or None
                timing = 'rss_vtt' if chemin.endswith('.vtt') else 'rss_srt'
                source['language'] = langue_st[:2]
    except Exception:
        verifier()
        cues = None
    if not cues:
        cues = _transcrire_macwhisper(normalise, dossier, source['language'], verifier)
        timing = 'macwhisper_srt'
    if not cues:
        raise RuntimeError('La transcription ne contient aucun segment lisible.')
    if not source['language']:
        source['language'] = detecter_langue(' '.join(c['text'] for c in cues))
    segments = [{'id': f's{i:04d}', 'text': c['text'], 'startMs': c['startMs'], 'endMs': c['endMs']}
                for i, c in enumerate(horodatage.regrouper_repliques(cues), 1)]
    pipeline.ecrire_json(str(segments_path), {'language': source['language'], 'timingSource': timing, 'segments': segments})
    precedent.update({'transcriptionKey': precedent['audioSha256'], 'segmentsSha256': empreinte(segments_path),
                      'audioFile': str(normalise), 'segmentsFile': str(segments_path), 'source': source,
                      'options': item['options'], 'timingSource': timing})
    pipeline.ecrire_json(str(cache), precedent)
    verifier()
    return precedent


def preparer_texte(item, dossier, etape, verifier):
    """Note My Mind ou texte importé : pas d'audio source, segments découpés dans le texte."""
    source = dict(item['source'])
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    etape('transcribe')
    morceaux = decouper_texte(source['text'])
    if not morceaux:
        raise RuntimeError('Le texte est vide.')
    source['language'] = detecter_langue(source['text'])
    segments_path = dossier / 'segments-source.json'
    segments = [{'id': f's{i:04d}', 'text': t, 'startMs': None, 'endMs': None} for i, t in enumerate(morceaux, 1)]
    pipeline.ecrire_json(str(segments_path), {'language': source['language'], 'timingSource': 'none', 'segments': segments})
    resultat = {'segmentsFile': str(segments_path), 'segmentsSha256': empreinte(segments_path), 'audioFile': None,
                'source': {k: v for k, v in source.items() if k != 'text'}, 'options': item['options'], 'timingSource': 'none'}
    pipeline.ecrire_json(str(dossier / 'source.json'), resultat)
    verifier()
    return resultat


def preparer_source(item, dossier, etape, verifier):
    """Aiguillage selon le type de demande : épisode de podcast, vidéo YouTube ou texte."""
    kind = item['source'].get('kind', 'episode')
    if kind == 'youtube':
        return preparer_youtube(item, dossier, etape, verifier)
    if kind == 'reflection':
        return preparer_texte(item, dossier, etape, verifier)
    if kind == 'dossier':
        import discover_dossier
        return discover_dossier.preparer(item, dossier, etape, verifier)
    return preparer(item, dossier, etape, verifier)
