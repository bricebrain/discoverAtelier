"""Client IA structuré et reprenable : Gemini, avec bascule automatique sur OpenAI s'il bloque."""
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import jsonschema
import pipeline

CONFIG = Path(__file__).with_name('config_ia.json')


class FournisseurIndisponible(RuntimeError):
    """Le fournisseur refuse ou ne répond pas (panne, clé, blocage, réseau) : on bascule sur l'autre."""


class QuotaAtteint(FournisseurIndisponible):
    pass


# Après un blocage de Gemini, les appels suivants vont directement à OpenAI pendant un moment
# (1 h après un quota, 15 min sinon) au lieu de réessayer Gemini à chaque fois.
REPLI = {'jusqua': 0.0, 'raison': ''}
VERROU_REPLI = threading.Lock()


def _marquer_repli(erreur):
    with VERROU_REPLI:
        REPLI['jusqua'] = time.time() + (3600 if isinstance(erreur, QuotaAtteint) else 900)
        REPLI['raison'] = str(erreur)[:200]


def etat_repli():
    """Texte affichable si Discover utilise OpenAI à la place de Gemini, sinon None."""
    with VERROU_REPLI:
        if REPLI['jusqua'] <= time.time():
            return None
        fin = time.strftime('%H:%M', time.localtime(REPLI['jusqua']))
        return f'OpenAI remplace Gemini jusqu’à {fin} — {REPLI["raison"]}'


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
    def cle(valeur):
        return valeur if isinstance(valeur, str) and len(valeur) >= 10 and '\n' not in valeur and '\r' not in valeur else None

    def modele(*valeurs):
        for v in valeurs:
            if isinstance(v, str) and v:
                return v if re.fullmatch(r'[a-zA-Z0-9._-]{1,100}', v) else None
        return None

    key = cle(os.environ.get('GEMINI_API_KEY') or discover.get('geminiApiKey') or cfg.get('geminiApiKey'))
    model = modele(discover.get('geminiModel'), cfg.get('discoverModel'), cfg.get('generatorModel'), 'gemini-3.1-flash-lite')
    openai_key = cle(os.environ.get('OPENAI_API_KEY') or discover.get('openaiApiKey') or cfg.get('openaiApiKey'))
    openai_model = modele(discover.get('openaiModel'), cfg.get('discoverOpenaiModel'), cfg.get('auditorModel'), 'gpt-5-mini')
    if not (key and model) and not (openai_key and openai_model):
        raise ValueError('Configurer une clé Gemini (ou OpenAI) et le modèle dans config_ia.json.')
    return {'key': key, 'model': model, 'judgeModel': modele(discover.get('geminiJudgeModel'), cfg.get('discoverJudgeModel')) or model,
            'openaiKey': openai_key, 'openaiModel': openai_model,
            'openaiJudgeModel': modele(discover.get('openaiJudgeModel')) or openai_model}


def empreinte(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Client:
    def __init__(self, dossier, verifier=lambda: None, config=None, transport=None, transport_openai=None):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.verifier = verifier
        self.config = config or configuration()
        self.transport = transport or self._generer
        self.transport_openai = transport_openai or self._generer_openai
        self.appels = {}

    def _fournisseurs(self, juge):
        """Gemini d'abord, OpenAI en secours ; l'inverse pendant une période de repli."""
        c = self.config
        liste = []
        if c.get('key') or self.transport != self._generer:
            liste.append(('gemini', c['judgeModel' if juge else 'model'], self.transport))
        if c.get('openaiKey'):
            liste.append(('openai', c.get('openaiJudgeModel' if juge else 'openaiModel') or c.get('openaiModel'), self.transport_openai))
        if len(liste) == 2 and etat_repli():
            liste.reverse()
        for _, modele, _ in liste:
            if not isinstance(modele, str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,100}', modele):
                raise ValueError('Modèle IA invalide.')
        return liste

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
            raise FournisseurIndisponible(f'Gemini indisponible (HTTP {e.code}).') from None
        except (OSError, ValueError):
            raise FournisseurIndisponible('Réponse Gemini inaccessible ou illisible.') from None
        blocage = (obj.get('promptFeedback') or {}).get('blockReason')
        if blocage:
            raise FournisseurIndisponible(f'Gemini a bloqué la demande ({blocage}).')
        candidate = (obj.get('candidates') or [{}])[0]
        if candidate.get('finishReason') in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII', 'RECITATION', 'IMAGE_SAFETY'):
            raise FournisseurIndisponible(f'Gemini a bloqué la réponse ({candidate["finishReason"]}).')
        if candidate.get('finishReason') != 'STOP':
            raise ValueError('Gemini a interrompu la réponse structurée.')
        text = ''.join(p.get('text', '') for p in candidate.get('content', {}).get('parts', []) if not p.get('thought'))
        usage = obj.get('usageMetadata') or {}
        return {'data': json.loads(text), 'inputTokens': usage.get('promptTokenCount', 0),
                'outputTokens': (usage.get('candidatesTokenCount') or 0) + (usage.get('thoughtsTokenCount') or 0)}

    def _generer_openai(self, prompt, schema, modele, etape='discover'):
        payload = {'model': modele, 'input': prompt, 'max_output_tokens': 24000,
                   'text': {'format': {'type': 'json_schema', 'name': 'discover_' + re.sub(r'[^a-zA-Z0-9_-]', '_', etape)[:50],
                                       'strict': False, 'schema': schema}}}
        if re.match(r'(gpt-[5-9]|o\d)', modele):
            payload['reasoning'] = {'effort': 'low'}
        req = urllib.request.Request('https://api.openai.com/v1/responses', data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.config['openaiKey']})
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                raw = response.read(3_000_001)
                if len(raw) > 3_000_000:
                    raise RuntimeError('Réponse OpenAI trop volumineuse.')
                obj = json.loads(raw)
        except urllib.error.HTTPError as e:
            e.close()
            if e.code == 429:
                raise QuotaAtteint('Quota OpenAI atteint.') from None
            raise FournisseurIndisponible(f'OpenAI indisponible (HTTP {e.code}).') from None
        except (OSError, ValueError):
            raise FournisseurIndisponible('Réponse OpenAI inaccessible ou illisible.') from None
        if obj.get('status') not in (None, 'completed'):
            raise ValueError('OpenAI a interrompu la réponse structurée.')
        text = obj.get('output_text') or ''.join(
            c.get('text', '') for o in obj.get('output') or [] for c in o.get('content') or []
            if c.get('type') in ('output_text', 'text'))
        for o in obj.get('output') or []:
            for c in o.get('content') or []:
                if c.get('type') == 'refusal':
                    raise FournisseurIndisponible('OpenAI a refusé la demande.')
        usage = obj.get('usage') or {}
        return {'data': json.loads(text), 'inputTokens': usage.get('input_tokens', 0), 'outputTokens': usage.get('output_tokens', 0)}

    def demander(self, etape, prompt, schema, valider=lambda _: None, juge=False, cache_schema=None):
        fournisseurs = self._fournisseurs(juge)
        # Une réponse déjà validée (de l'un ou l'autre fournisseur) est réutilisée telle quelle.
        for _, modele, _ in fournisseurs:
            key = empreinte([modele, prompt, cache_schema or schema])
            saved = pipeline.lire_json(str(self.dossier / (key + '.json')))
            if saved:
                try:
                    jsonschema.validate(saved['data'], schema)
                    valider(saved['data'])
                    # Réponse déjà payée lors d'une préparation précédente : marquée pour ne pas être recomptée.
                    self.appels[key] = {**saved['usage'], 'cached': True}
                    return saved['data']
                except (KeyError, ValueError, jsonschema.ValidationError):
                    pass
        if len(self.appels) >= 80 or sum(v.get('inputTokens', 0) + v.get('outputTokens', 0) for v in self.appels.values()) > 240_000:
            raise RuntimeError('Budget maximal de préparation atteint. Étapes conservées ; vérifier la demande avant de réessayer.')
        erreurs = []
        for nom, modele, transport in fournisseurs:
            try:
                return self._essayer(etape, prompt, schema, valider, cache_schema, nom, modele, transport)
            except FournisseurIndisponible as erreur:
                erreurs.append(erreur)
                if nom == 'gemini' and len(fournisseurs) > 1:
                    _marquer_repli(erreur)
        if any(isinstance(e, QuotaAtteint) for e in erreurs):
            raise QuotaAtteint(' / '.join(str(e) for e in erreurs) + ' Sources et étapes conservées.')
        raise erreurs[-1]

    def _essayer(self, etape, prompt, schema, valider, cache_schema, nom, modele, transport):
        key = empreinte([modele, prompt, cache_schema or schema])
        correction = ''
        last_error = ''
        for tentative in range(3):
            self.verifier()
            try:
                result = transport(prompt + correction, schema, modele, etape) if nom == 'openai' else transport(prompt + correction, schema, modele)
            except (ValueError, json.JSONDecodeError):
                correction = '\nReturn valid complete JSON matching the schema.'
                continue
            self.verifier()
            usage = {'stage': etape, 'provider': nom, 'model': modele,
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
            pipeline.ecrire_json(str(self.dossier / (key + '.json')), {'data': result['data'], 'usage': usage})
            return result['data']
        raise ValueError('Réponse structurée invalide après trois essais : ' + etape + ' — ' + last_error)

    def statistiques(self):
        utilises = sorted({v.get('provider', 'gemini') for v in self.appels.values()}) or ['gemini']
        modeles = sorted({v['model'] for v in self.appels.values() if v.get('model')})
        return {'provider': '+'.join(utilises), 'model': ', '.join(modeles) or self.config.get('model') or self.config.get('openaiModel'),
                'calls': len(self.appels),
                'inputTokens': sum(v.get('inputTokens', 0) for v in self.appels.values()),
                'outputTokens': sum(v.get('outputTokens', 0) for v in self.appels.values())}
