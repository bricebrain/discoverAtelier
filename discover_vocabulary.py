"""Cache facultatif du référentiel EnglishFluency pour les seuls indicateurs de langue."""
import json
import time
import urllib.request
from pathlib import Path

import bundles
import pipeline
from discover_evaluation import normaliser


def charger(folder):
    cache = Path(folder) / 'frequent-words.json'
    old = pipeline.lire_json(str(cache))
    if old and time.time() - old.get('at', 0) < 86400:
        return set(old['words'])
    config, erreur = bundles.charger_config_import()
    if erreur:
        return set(old['words']) if old else set()
    words = set()
    try:
        for offset in range(0, 20000, 1000):
            request = urllib.request.Request(config['workerUrl'] + f'/words?limit=1000&offset={offset}',
                      headers={'Authorization': 'Bearer ' + config['apiSecret'], 'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read(5_000_001)
                if len(raw) > 5_000_000:
                    raise ValueError('Référentiel trop volumineux.')
                page = json.loads(raw)['words']
            for row in page:
                value = row.get('word') or row.get('en')
                if isinstance(value, str):
                    words.add(normaliser(value))
            if len(page) < 1000:
                break
        if words:
            pipeline.ecrire_json(str(cache), {'at': time.time(), 'words': sorted(words)})
    except (OSError, ValueError, KeyError):
        return set(old['words']) if old else set()
    return words
