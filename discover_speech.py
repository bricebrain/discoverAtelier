"""Choix du moteur pour une préparation entière, coût avant audio et repli Kokoro sans double appel."""
from datetime import datetime, timezone
from pathlib import Path

import discover_audio
from discover_citations import nettoyer_segments
import discover_deepgram
import pipeline
from discover_ai import empreinte
from discover_download import empreinte as file_hash
from discover_source import commande, ffmpeg
from discover_tts_budget import AppelIncertain, Budget, BudgetDepasse, MICRODOLLARS_PER_CHARACTER
from discover_tts_settings import settings


class Session:
    def __init__(self, scripts, root, config, folder, title='', long_minutes=None):
        self.root, self.folder = Path(root), Path(folder)
        self.config = {**config, 'tts': settings(config)}
        self.provider, self.speeds = self.config['tts']['provider'], None
        self.reason = None
        self.ledger = Budget(self.root / '.deepgram')
        scripts = [nettoyer_segments(script) for script in scripts]
        parts = [part for script in scripts for part in discover_deepgram.plan(
            script, self.root / '.deepgram', self.config['tts']['voice'], self.config['tts']['speed'])]
        missing = {p['key']: p for p in parts if not p['cached']}
        needed = sum(p['characters'] for p in missing.values())
        self.estimate = {'title': title, 'requestedProvider': self.provider, 'provider': self.provider,
                         'voice': self.config['tts']['voice'], 'characters': sum(p['characters'] for p in parts),
                         'newCharacters': needed, 'estimatedUsd': needed * MICRODOLLARS_PER_CHARACTER / 1_000_000,
                         'createdAt': datetime.now(timezone.utc).isoformat(), 'status': 'estimated'}
        if self.provider == 'deepgram' and long_minutes:
            # Choix délibéré, pas une panne : les longues sources restent sur le Mac en voix locale.
            self.provider, self.reason = 'kokoro', f'Source longue ({round(long_minutes)} min) : voix locale Kokoro, sans coût Deepgram.'
            self.estimate.update(provider='kokoro', fallbackReason=self.reason, estimatedUsd=0)
        elif self.provider == 'deepgram':
            if needed and not config.get('deepgramApiKey'):
                self.fallback('Clé Deepgram absente.')
            elif self.estimate['estimatedUsd'] > self.ledger.status(self.config['tts']['monthlyLimitUsd'])['remainingUsd'] + 1e-9:
                self.fallback('Plafond mensuel insuffisant pour cette préparation complète.')
            elif any(self.ledger.attempted(key) for key in missing):
                self.fallback('Un fragment a déjà été envoyé sans cache valide ; aucun nouvel appel payant automatique.')
        self.write()

    def fallback(self, reason):
        if not self.config['tts']['fallback']:
            raise BudgetDepasse(reason)
        self.provider, self.reason = 'kokoro', reason
        self.estimate.update(provider='kokoro', fallbackReason=reason)
        self.write()

    def write(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        pipeline.ecrire_json(str(self.folder / 'audio-estimate.json'), self.estimate)

    def kokoro_speeds(self, verifier):
        if self.speeds is None:
            self.speeds = discover_audio.vitesses()
        return self.speeds

    def generate(self, segments, folder, name, verifier, speeds=None):
        segments = nettoyer_segments(segments)
        if self.provider == 'deepgram':
            try:
                result = self.deepgram(segments, Path(folder), name, verifier)
                self.estimate.update(status='generated', provider='deepgram')
                self.write()
                return result
            except (BudgetDepasse, AppelIncertain, discover_deepgram.DeepgramIndisponible) as error:
                self.fallback(str(error))
        result = discover_audio.executer(segments, folder, name, verifier, speeds or self.kokoro_speeds(verifier))
        self.estimate.update(status='generated', provider='kokoro')
        self.write()
        return {**result, 'origin': 'kokoro', 'timingSource': 'kokoro', 'fallbackReason': self.reason}

    def deepgram(self, segments, folder, name, verifier):
        folder.mkdir(parents=True, exist_ok=True)
        options = self.config['tts']
        signature = empreinte(['deepgram-paced-v2', segments, options['voice'], options['speed'],
                               discover_deepgram.INTRO_PAUSE_SECONDS, discover_deepgram.PARAGRAPH_PAUSE_SECONDS])
        record_path, mp3 = folder / (name + '.audio.json'), folder / (name + '.mp3')
        timings, wav = folder / (name + '.timings.json'), folder / (name + '.wav')
        record = pipeline.lire_json(str(record_path))
        if (record and record.get('signature') == signature and mp3.exists() and timings.exists()
                and record.get('sha256') == file_hash(mp3) and record.get('timingsSha256') == file_hash(timings)):
            verifier()
            return record
        result = discover_deepgram.assemble(segments, self.root / '.deepgram', self.config, wav, timings, verifier)
        part = mp3.with_suffix('.part.mp3')
        try:
            commande([ffmpeg(), '-nostdin', '-y', '-v', 'error', '-i', str(wav), '-ac', '1', '-b:a', '128k', str(part)], verifier)
            verifier()
            part.replace(mp3)
        finally:
            part.unlink(missing_ok=True)
        # Les timings proviennent du nombre d'échantillons assemblés, pas d'une réestimation du texte.
        record = {**result, 'signature': signature, 'file': str(mp3), 'timingsFile': str(timings),
                  'timingsSha256': file_hash(timings), 'sha256': file_hash(mp3),
                  'origin': 'deepgram', 'timingSource': 'deepgram', 'voice': options['voice'], 'speed': options['speed']}
        pipeline.ecrire_json(str(record_path), record)
        wav.unlink(missing_ok=True)
        return record
