"""Réglages audio Discover ; la clé reste exclusivement dans le fichier privé de l'Atelier."""
import math
import threading
from pathlib import Path

import pipeline
import discover_cible
from discover_tts_budget import Budget

VOICES = {'arcas': 'Arcas · américain', 'cora': 'Cora · américain', 'vesta': 'Vesta · américain', 'draco': 'Draco · britannique'}
DEFAULTS = {'provider': 'kokoro', 'voice': 'arcas', 'monthlyLimitUsd': 10.0, 'speed': 1.0, 'fallback': True}
LOCK = threading.RLock()


def settings(config):
    value = {**DEFAULTS, **(config.get('tts') or {})}
    if value['provider'] not in ('kokoro', 'deepgram') or value['voice'] not in VOICES:
        raise ValueError('Moteur ou voix audio invalide.')
    for key, minimum, maximum in [('monthlyLimitUsd', 0, 100), ('speed', .7, 1.5)]:
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError('Budget de 0 à 100 USD et débit de 0,7 à 1,5 attendus.')
    if not isinstance(value['fallback'], bool):
        raise ValueError('Repli Kokoro : booléen attendu.')
    value['speed'] = float(value['speed'])
    value['monthlyLimitUsd'] = float(value['monthlyLimitUsd'])
    return {key: value[key] for key in DEFAULTS}


def save(body):
    if set(body) - set(DEFAULTS):
        raise ValueError('Réglage audio inconnu. Les clés API ne se saisissent pas dans cette page.')
    with LOCK:
        config = discover_cible.charger_config()
        config['tts'] = settings({**config, 'tts': {**(config.get('tts') or {}), **body}})
        pipeline.ecrire_json(str(discover_cible.CONFIG), config)
        discover_cible.CONFIG.chmod(0o600)
        return config


def status(root, config=None):
    config = config if config is not None else discover_cible.charger_config()
    value = settings(config)
    plans = sorted(Path(root).glob('*/prepared-*/audio-estimate.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    return {'settings': value, 'voices': VOICES, 'keyConfigured': bool(config.get('deepgramApiKey')),
            'pricePerThousandUsd': .03, 'budget': Budget(Path(root) / '.deepgram').status(value['monthlyLimitUsd']),
            'preparations': [doc for p in plans if (doc := pipeline.lire_json(str(p)))]}
