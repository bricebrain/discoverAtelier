"""Client Gemini structuré et reprenable ; aucune dépendance au chantier vocabulaire."""
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema
import pipeline

CONFIG = Path(__file__).with_name('config_ia.json')


class QuotaAtteint(RuntimeError):
    pass


def configuration():
    try:
        cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    except (OSError, ValueError):
        raise ValueError('Configuration IA illisible.') from None
    if not isinstance(cfg, dict):
        raise ValueError('Objet JSON requis dans la configuration IA.')
    path = Path(__file__).with_name('config_discover.json')
    try:
        discover = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, ValueError):
        raise ValueError('Configuration Discover illisible.') from None
    if not isinstance(discover, dict):
        raise ValueError('Objet JSON requis dans la configuration Discover.')
    key = os.environ.get('GEMINI_API_KEY') or discover.get('geminiApiKey') or cfg.get('geminiApiKey')
    model = discover.get('geminiModel') or cfg.get('discoverModel') or cfg.get('generatorModel') or 'gemini-3.1-flash-lite'
    if not isinstance(key, str) or len(key) < 10 or '\n' in key or '\r' in key or not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,100}', model):
        raise ValueError('Configurer la clé Gemini et le modèle dans config_ia.json.')
    return {'key': key, 'model': model, 'judgeModel': discover.get('geminiJudgeModel') or cfg.get('discoverJudgeModel') or model}


def empreinte(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Client:
    def __init__(self, dossier, verifier=lambda: None, config=None, transport=None):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.verifier = verifier
        self.config = config or configuration()
        self.transport = transport or self._generer
        self.appels = {}

    def _generer(self, prompt, schema, modele):
        url = 'https://generativelanguage.googleapis.com/v1beta/models/' + modele + ':generateContent'
        payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                   'generationConfig': {'temperature': 0.1, 'maxOutputTokens': 24000,
                                        'responseMimeType': 'application/json', 'responseJsonSchema': schema}}
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json', 'x-goog-api-key': self.config['key']})
        try:
            with urllib.request.urlopen(req, timeout=240) as response:
                raw = response.read(3_000_001)
                if len(raw) > 3_000_000:
                    raise RuntimeError('Réponse Gemini trop volumineuse.')
                obj = json.loads(raw)
        except urllib.error.HTTPError as e:
            e.close()
            if e.code == 429:
                raise QuotaAtteint('Quota Gemini atteint. Sources et étapes conservées.') from None
            raise RuntimeError(f'Gemini indisponible (HTTP {e.code}).') from None
        except (OSError, ValueError):
            raise RuntimeError('Réponse Gemini inaccessible ou illisible.') from None
        candidate = (obj.get('candidates') or [{}])[0]
        if candidate.get('finishReason') != 'STOP':
            raise ValueError('Gemini a interrompu la réponse structurée.')
        text = ''.join(p.get('text', '') for p in candidate.get('content', {}).get('parts', []) if not p.get('thought'))
        usage = obj.get('usageMetadata') or {}
        return {'data': json.loads(text), 'inputTokens': usage.get('promptTokenCount', 0),
                'outputTokens': (usage.get('candidatesTokenCount') or 0) + (usage.get('thoughtsTokenCount') or 0)}

    def demander(self, etape, prompt, schema, valider=lambda _: None, juge=False, cache_schema=None):
        modele = self.config['judgeModel' if juge else 'model']
        if not isinstance(modele, str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,100}', modele):
            raise ValueError('Modèle Gemini invalide.')
        key = empreinte([modele, prompt, cache_schema or schema])
        path = self.dossier / (key + '.json')
        saved = pipeline.lire_json(str(path))
        if saved:
            try:
                jsonschema.validate(saved['data'], schema)
                valider(saved['data'])
                self.appels[key] = saved['usage']
                return saved['data']
            except (KeyError, ValueError, jsonschema.ValidationError):
                pass
        if len(self.appels) >= 80 or sum(v.get('inputTokens', 0) + v.get('outputTokens', 0) for v in self.appels.values()) > 240_000:
            raise RuntimeError('Budget maximal de préparation atteint. Étapes conservées ; vérifier la demande avant de réessayer.')
        correction = ''
        last_error = ''
        for tentative in range(3):
            self.verifier()
            try:
                result = self.transport(prompt + correction, schema, modele)
            except (ValueError, json.JSONDecodeError):
                correction = '\nReturn valid complete JSON matching the schema.'
                continue
            self.verifier()
            usage = {'stage': etape, 'provider': 'gemini', 'model': modele,
                     'inputTokens': result.get('inputTokens', 0), 'outputTokens': result.get('outputTokens', 0)}
            self.appels[key + '-attempt-' + str(tentative)] = usage
            try:
                jsonschema.validate(result['data'], schema)
                valider(result['data'])
            except (ValueError, jsonschema.ValidationError) as erreur:
                last_error = str(erreur).splitlines()[0][:300]
                correction = '\nCORRECTION REQUIRED: ' + last_error + '\nPrevious invalid output: ' + json.dumps(result['data'], ensure_ascii=False) + '\nReturn a complete corrected JSON, no commentary.'
                continue
            self.appels.pop(key + '-attempt-' + str(tentative), None)
            self.appels[key] = usage
            pipeline.ecrire_json(str(path), {'data': result['data'], 'usage': usage})
            return result['data']
        raise ValueError('Réponse structurée invalide après trois essais : ' + etape + ' — ' + last_error)

    def statistiques(self):
        return {'provider': 'gemini', 'model': self.config['model'], 'calls': len(self.appels),
                'inputTokens': sum(v.get('inputTokens', 0) for v in self.appels.values()),
                'outputTokens': sum(v.get('outputTokens', 0) for v in self.appels.values())}
