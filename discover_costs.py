"""Coûts visibles : ce que chaque préparation et chaque mois consomme (Gemini, OpenAI en repli, Deepgram).

Aucune clé ne sort d'ici : seule la clé « pricing » (tarifs) de la configuration est lue."""
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import discover_cible
import pipeline
from discover_ai import empreinte
from discover_tts_budget import Budget
from discover_tts_settings import settings

# Tarifs par défaut PRUDENTS, en USD par million de jetons (entrée puis sortie) — À VÉRIFIER sur les
# tarifs officiels de chaque modèle, puis ajuster sans toucher au code via la clé « pricing » de
# config_discover.json. « * » s'applique à tout modèle inconnu, en majorant pour ne jamais sous-estimer.
TARIFS_DEFAUT = {
    'gemini-3.1-flash-lite': {'inputUsdPerMillion': 0.20, 'outputUsdPerMillion': 0.80},
    'gpt-5-mini': {'inputUsdPerMillion': 0.25, 'outputUsdPerMillion': 2.00},
    '*': {'inputUsdPerMillion': 1.00, 'outputUsdPerMillion': 4.00},
}
COLONNES = ('key', 'item_id', 'title', 'month', 'created_at', 'gemini_micro', 'gemini_in', 'gemini_out',
            'openai_micro', 'openai_in', 'openai_out', 'deepgram_micro', 'deepgram_chars', 'voice',
            'tts_provider', 'fallback_reason', 'models')


def _prix(valeur):
    """Une entrée de tarifs valide : deux nombres finis entre 0 et 1 000 USD par million de jetons."""
    if not isinstance(valeur, dict):
        return None
    resultat = {}
    for cle in ('inputUsdPerMillion', 'outputUsdPerMillion'):
        nombre = valeur.get(cle)
        if isinstance(nombre, bool) or not isinstance(nombre, (int, float)) or not 0 <= nombre <= 1000:
            return None
        resultat[cle] = float(nombre)
    return resultat


def tarifs(config=None):
    """Tarifs effectifs : les valeurs prudentes par défaut, complétées par « pricing » dans la configuration."""
    resultat = dict(TARIFS_DEFAUT)
    personnalises = (config or {}).get('pricing')
    if isinstance(personnalises, dict):
        for modele, prix in personnalises.items():
            nom = modele if isinstance(modele, str) and re.fullmatch(r'[a-zA-Z0-9.*_-]{1,100}', modele) else None
            valeur = _prix(prix)
            if nom and valeur:
                resultat[nom] = valeur
    return resultat


def _nombre(valeur):
    return valeur if isinstance(valeur, int) and not isinstance(valeur, bool) and valeur > 0 else 0


def _montant(valeur):
    """Un montant USD lu dans un fichier JSON : flottant positif, 0 si absent ou invalide."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return 0.0
    return max(0.0, float(valeur))


def mois(date_ref=None, precedents=0):
    """Mois UTC « YYYY-MM », celui de `date_ref` (maintenant par défaut) ou les précédents demandés."""
    jour = (date_ref or datetime.now(timezone.utc)).date().replace(day=1)
    for _ in range(precedents):
        jour = (jour - timedelta(days=1)).replace(day=1)
    return jour.strftime('%Y-%m')


def _deepgram_par_mois(dossier):
    """Coûts Deepgram réellement engagés, lus dans le registre du budget (lecture seule, jamais d'écriture)."""
    path = Path(dossier) / 'usage.sqlite'
    if not path.exists():
        return {}
    try:
        db = sqlite3.connect('file:' + quote(str(path)) + '?mode=ro', uri=True)
        try:
            lignes = db.execute('SELECT month, COALESCE(SUM(cost_micro),0) FROM requests GROUP BY month').fetchall()
        finally:
            db.close()
        return {m: v for m, v in lignes}
    except sqlite3.Error:
        return {}


class Registre:
    """Une ligne par préparation aboutie ; la clé stable rend une reprise idempotente (pas de double comptage)."""

    def __init__(self, root, maintenant=None):
        self.path = Path(root) / 'costs.sqlite'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.maintenant = maintenant
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS preparations (
                key TEXT PRIMARY KEY, item_id TEXT NOT NULL, title TEXT NOT NULL, month TEXT NOT NULL,
                created_at TEXT NOT NULL, gemini_micro INTEGER NOT NULL, gemini_in INTEGER NOT NULL, gemini_out INTEGER NOT NULL,
                openai_micro INTEGER NOT NULL, openai_in INTEGER NOT NULL, openai_out INTEGER NOT NULL,
                deepgram_micro INTEGER NOT NULL, deepgram_chars INTEGER NOT NULL, voice TEXT NOT NULL,
                tts_provider TEXT NOT NULL, fallback_reason TEXT NOT NULL, models TEXT NOT NULL)''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def enregistrer(self, item, appels, folder, config=None):
        """Consigne les coûts d'une préparation : appels IA depuis `Client.appels`, voix depuis l'estimation audio.

        Le coût Deepgram repris ici est l'estimation engagée (nouveaux caractères) quand la voix a bien été
        produite par Deepgram ; le registre du budget reste la source exacte du total mensuel."""
        folder = Path(folder)
        grille = tarifs(config)
        totaux = {'gemini': [0, 0, 0], 'openai': [0, 0, 0]}  # micro-USD, jetons d'entrée, jetons de sortie.
        modeles = set()
        appels = appels if isinstance(appels, dict) else {}
        for appel in appels.values():
            if not isinstance(appel, dict):
                continue
            fournisseur = appel.get('provider') if appel.get('provider') in totaux else 'gemini'
            entree, sortie = _nombre(appel.get('inputTokens')), _nombre(appel.get('outputTokens'))
            modele = appel.get('model')
            tarif = grille.get(modele) or grille['*']
            if isinstance(modele, str) and modele:
                modeles.add(modele)
            totaux[fournisseur][0] += round(entree * tarif['inputUsdPerMillion'] + sortie * tarif['outputUsdPerMillion'])
            totaux[fournisseur][1] += entree
            totaux[fournisseur][2] += sortie
        audio = pipeline.lire_json(str(folder / 'audio-estimate.json')) or {}
        deepgram = audio.get('provider') == 'deepgram'
        instant = self.maintenant or datetime.now(timezone.utc)
        # Une régénération (révision) est une nouvelle dépense ; une simple reprise conserve la même clé.
        cle = empreinte([item.get('id'), item.get('options'),
                         (pipeline.lire_json(str(folder / 'revision.json')) or {}).get('revision', 0)])
        ligne = (cle, str(item.get('id') or ''), str(item.get('source', {}).get('title', ''))[:300],
                 mois(instant), instant.isoformat(),
                 totaux['gemini'][0], totaux['gemini'][1], totaux['gemini'][2],
                 totaux['openai'][0], totaux['openai'][1], totaux['openai'][2],
                 round(_montant(audio.get('estimatedUsd')) * 1_000_000) if deepgram else 0,
                 _nombre(audio.get('newCharacters')) if deepgram else 0,
                 str(audio.get('voice') or ''), str(audio.get('provider') or ''),
                 str(audio.get('fallbackReason') or ''), json.dumps(sorted(modeles)))
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO preparations VALUES (' + ','.join('?' * len(COLONNES)) + ')', ligne)

    def ia_par_mois(self):
        """Totaux IA (micro-USD) par mois, pour additionner avec le registre Deepgram."""
        with self.connection() as db:
            lignes = db.execute('SELECT month, COALESCE(SUM(gemini_micro),0), COALESCE(SUM(openai_micro),0) '
                                'FROM preparations GROUP BY month').fetchall()
        return {m: {'geminiMicro': g, 'openaiMicro': o} for m, g, o in lignes}

    def dernieres(self, limite=20):
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            return db.execute('SELECT * FROM preparations ORDER BY created_at DESC LIMIT ?', (limite,)).fetchall()


def enregistrer(item, appels, folder, root, config=None):
    """Point d'entrée appelé en fin de préparation (discover_preparation) : une ligne, remplacée si reprise."""
    Registre(root).enregistrer(item, appels, folder, config)


def _ligne_vers_dict(ligne):
    gemini = ligne['gemini_micro'] / 1_000_000
    openai = ligne['openai_micro'] / 1_000_000
    deepgram = ligne['deepgram_micro'] / 1_000_000
    return {'id': ligne['item_id'], 'title': ligne['title'], 'createdAt': ligne['created_at'], 'month': ligne['month'],
            'geminiUsd': round(gemini, 6), 'openaiUsd': round(openai, 6), 'deepgramUsd': round(deepgram, 6),
            'totalUsd': round(gemini + openai + deepgram, 6),
            'geminiTokens': ligne['gemini_in'] + ligne['gemini_out'], 'openaiTokens': ligne['openai_in'] + ligne['openai_out'],
            'deepgramCharacters': ligne['deepgram_chars'], 'voice': ligne['voice'], 'ttsProvider': ligne['tts_provider'],
            'fallbackReason': ligne['fallback_reason'] or None, 'models': json.loads(ligne['models'])}


def rapport(root, config=None, maintenant=None):
    """Mois en cours et précédent, vingt dernières préparations, plafond Deepgram : tout ce qu'affiche l'Atelier."""
    config = config if config is not None else discover_cible.charger_config()
    root = Path(root)
    registre = Registre(root, maintenant=maintenant)
    ia = registre.ia_par_mois()
    deepgram = _deepgram_par_mois(root / '.deepgram')
    months = []
    for m in (mois(maintenant), mois(maintenant, precedents=1)):
        vide = {'geminiMicro': 0, 'openaiMicro': 0}
        gemini, openai = ia.get(m, vide)['geminiMicro'] / 1_000_000, ia.get(m, vide)['openaiMicro'] / 1_000_000
        voix = deepgram.get(m, 0) / 1_000_000
        months.append({'month': m, 'geminiUsd': round(gemini, 6), 'openaiUsd': round(openai, 6),
                       'deepgramUsd': round(voix, 6), 'totalUsd': round(gemini + openai + voix, 6)})
    reglages = settings(config)
    budget = Budget(root / '.deepgram').status(reglages['monthlyLimitUsd'])
    return {'months': months, 'budget': {**budget, 'limitUsd': reglages['monthlyLimitUsd']},
            'pricingConfigured': isinstance(config.get('pricing'), dict) and bool(config['pricing']),
            'tarifs': tarifs(config), 'preparations': [_ligne_vers_dict(l) for l in registre.dernieres(20)]}
