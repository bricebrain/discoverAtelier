"""Services de test A5 : aucun téléchargement, fournisseur IA ou Worker réel."""
import copy
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

import discover_cible
import discover_costs
import discover_preparation
import discover_queue
import discover_source
from discover_ai import Client, FournisseurIndisponible
from manifeste_validation import valider_manifeste

REQUEST = '11111111-1111-4111-8111-111111111111'
NOTE = '22222222-2222-4222-8222-222222222222'
ARTICLE = '33333333-3333-4333-8333-333333333333'
DOSSIER = '44444444-4444-4444-8444-444444444444'
EPISODE = 'a' * 20
VIDEO = 'dQw4w9WgXcQ'
TEXT = 'The city plans to add buses next month. The plan aims to cut traffic and help people get to work.'
QUESTIONS = [
    {'question': question, 'choices': ['To cut traffic', 'To close roads', 'To sell cars'],
     'correctChoice': 0, 'explanation': 'The plan aims to cut traffic.', 'segmentIndex': i}
    for i, question in enumerate(['Why add buses?', 'What is the aim of the plan?', 'How could the plan help?'])
]


def demande(kind):
    sources = [
        {'kind': 'episode', 'type': 'episode', 'ref': EPISODE, 'title': 'Podcast',
         'language': 'en', 'audioUrl': 'https://publisher.example/audio.mp3'},
        {'kind': 'youtube', 'type': 'youtube', 'ref': VIDEO, 'videoId': VIDEO, 'title': 'Video',
         'language': 'en', 'url': 'https://www.youtube.com/watch?v=' + VIDEO},
        {'kind': 'reflection', 'type': 'reflection', 'ref': NOTE, 'title': 'Personal note',
         'text': TEXT, 'origin': 'personal'},
        {'kind': 'reflection', 'type': 'reflection', 'ref': ARTICLE, 'title': 'Article',
         'text': TEXT, 'origin': 'article', 'sourceName': 'City News'},
        {'kind': 'content', 'type': 'content', 'ref': 'youtube-' + 'b' * 20, 'title': 'Prepared video',
         'language': 'en', 'publicationId': 'previous-publication', 'variantKey': 'en-source',
         'segments': [{'id': 's0001', 'text': TEXT, 'startMs': 500, 'endMs': 5000}]},
    ]
    if kind == 'dossier':
        source = {'kind': 'dossier', 'title': 'Transport dossier', 'sources': [
            {**s, **({'type': 'episode', 'ref': 'b' * 20} if s['kind'] == 'youtube' else {}),
             'id': f'd{i}', 'capturedAt': '2026-10-19T10:00:00.000Z'}
            for i, s in enumerate(sources, 1)]}
        ref = DOSSIER
    else:
        source = sources[{'episode': 0, 'youtube': 1, 'reflection': 2, 'article': 3}[kind]]
        ref = source['ref']
    return {'id': REQUEST, 'kind': source['kind'], 'ref': ref, 'source': source,
            'options': {'coverage': 'full', 'targetMinutes': None, 'level': 'B1', 'style': 'narration',
                        'faithful': False, 'keepOriginalCopy': False}}


class FauxIA:
    """Transport structuré, soumis aux vrais schémas et validateurs du Client."""
    def __init__(self, quiz='valid'):
        self.quiz = quiz
        self.prompts = []

    def __call__(self, prompt, schema, model):
        self.prompts.append(prompt)
        props = schema['properties']
        if 'summary' in props:
            data = {'summary': 'Transport plan', 'speakers': [], 'properNames': [], 'glossary': []}
        elif 'items' in props:
            source = json.loads(prompt.split('<source_data>')[1].split('</source_data>')[0])
            data = {'items': [{'type': 'fact', 'text': s['text'], 'sourceSegments': [s['id']]}
                              for s in source['segments']]}
        elif 'tooShortForSubject' in props:
            source = json.loads(prompt.split('<source_data>')[1].split('</source_data>')[0])
            facts = source['extraction']['items']
            paragraphs = max(3, schema['properties']['segments']['minItems'])  # le schéma donne une fourchette ; le quiz factice vise 3 paragraphes
            groups = [facts[i::paragraphs] or [facts[i % len(facts)]] for i in range(paragraphs)]
            data = {'segments': [{'text': ' '.join(f['text'] for f in group), 'fr': 'Le plan vise à réduire la circulation.',
                                  'speaker': 'Narrator', 'sourceSegments': [r for f in group for r in f['sourceSegments']]}
                                 for group in groups], 'keyVocab': [],
                    'tooShortForSubject': False, 'recommendedMinutes': None}
        elif 'verdict' in props:
            source = json.loads(prompt.split('<source_data>')[1].split('</source_data>')[0])
            data = {'verdict': 'ok', 'unsupportedClaims': [], 'omittedKeyPoints': [],
                    'lostNuances': [], 'promotionsRemaining': [], 'languageWarnings': [],
                    'factChecks': [{'factIndex': i, 'presentInScript': True, 'reason': 'Cited in the script.'}
                                   for i in range(len(source['extractedFacts']))]}
        elif 'questions' in props:
            if self.quiz == 'unavailable':
                raise FournisseurIndisponible('Panne simulée')
            data = {'questions': copy.deepcopy(QUESTIONS)}
            if self.quiz == 'invalid':
                data['questions'][0]['segmentIndex'] = 99999
        else:
            raise AssertionError('Étape IA inattendue')
        return {'data': data, 'inputTokens': 1000, 'outputTokens': 500}


class FauxWorker:
    """Bail, déclaration, upload vérifié et commit, avec contrôle de l'ordre des opérations."""
    def __init__(self, item):
        self.item = copy.deepcopy(item)
        self.token = 'lease-simulated'
        self.events, self.uploads = [], {}
        self.manifest = None
        self.ready = False
        self.lose_lease_at = None
        self.consumer = None

    def __call__(self, config, method, path, data=None, fichier=None, headers=None):
        self.events.append((method, path, copy.deepcopy(data)))
        if path == '/atelier/queue/lease':
            assert data['owner'] == 'mac-test' and not data['sourceOnly']
            if self.ready:
                self.consumer.stop.set()
                return {'item': None}
            assert not any(p == path for _, p, _ in self.events[:-1]), 'Une seule prise de bail attendue'
            return {'item': {**copy.deepcopy(self.item), 'leaseToken': self.token}}
        if path.endswith('/heartbeat'):
            assert data['leaseToken'] == self.token and not self.ready
            if data['stage'] == self.lose_lease_at:
                raise discover_cible.ErreurDiscover(409, 'lease_lost')
            return {}
        if method == 'GET' and path.endswith('/manifest'):
            if not self.ready:
                raise discover_cible.ErreurDiscover(404, 'not_found')
            return {'manifest': self.manifest}
        if method == 'POST' and path == '/atelier/publications':
            assert data['leaseToken'] == self.token and data['queueItemId'] == self.item['id']
            assert self.consumer.etape == 'publish'
            valider_manifeste(data['manifest'])
            self.manifest = copy.deepcopy(data['manifest'])
            return {'status': 'uploading', 'publicationId': 'simulation', 'missing': list(self.manifest['files'])}
        if path.endswith('/fail'):
            assert data['leaseToken'] == self.token
            return {}
        assert headers['X-Discover-Lease-Token'] == self.token
        if method == 'PUT' and '/files/' in path:
            name = unquote(path.split('/files/')[1])
            raw = Path(fichier).read_bytes()
            meta = self.manifest['files'][name]
            assert len(raw) == meta['size'] == int(headers['Content-Length'])
            assert hashlib.sha256(raw).hexdigest() == meta['sha256'] == headers['x-content-sha256']
            self.uploads[name] = raw
            return {}
        if method == 'POST' and path.endswith('/commit'):
            assert set(self.uploads) == set(self.manifest['files'])
            self.ready = True
            return {'status': 'ready', 'publicationId': 'simulation'}
        raise AssertionError('Route simulée inattendue : ' + path)


class Simulation:
    def __init__(self, root, kind, quiz='valid'):
        self.root = Path(root)
        self.item = demande(kind)
        self.worker = FauxWorker(self.item)
        self.ai = FauxIA(quiz)
        self.media = []
        self.quiz = quiz
        self.client = None

    def source_media(self, item, folder, etape, verifier):
        self.media.append((item['source']['kind'], Path(folder).name))
        for stage in ('download', 'normalize', 'transcribe'):
            etape(stage)
            verifier()
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        segments = folder / 'segments-source.json'
        segments.write_text(json.dumps({'language': 'en', 'timingSource': 'rss_srt', 'segments': [
            {'id': 's0001', 'text': TEXT, 'startMs': 0, 'endMs': 10_000}]}))
        audio = folder / 'source.mp3'
        audio.write_bytes(b'ID3-source-simulated')
        return {'segmentsFile': str(segments), 'audioFile': str(audio), 'source': item['source'],
                'segmentsSha256': hashlib.sha256(segments.read_bytes()).hexdigest()}

    def voix(self, segments, folder, key, verifier, speeds):
        verifier()
        audio, timings = Path(folder) / (key + '.mp3'), Path(folder) / (key + '-timings.json')
        audio.write_bytes(b'ID3-voice-simulated')
        timings.write_text(json.dumps([{'id': s['id'], 'startMs': i * 1000, 'endMs': (i + 1) * 1000}
                                       for i, s in enumerate(segments)]))
        return {'file': str(audio), 'timingsFile': str(timings), 'durationMs': len(segments) * 1000,
                'origin': 'deepgram', 'timingSource': 'deepgram'}

    def executer(self):
        consumer = discover_queue.FileDiscover(self.root, requete=self.worker)
        self.worker.consumer = consumer
        self.consumer = consumer
        consumer.owner = 'mac-test'
        consumer.config = {'workerUrl': 'https://worker.invalid', 'autoPublish': False,
                           'comprehensionQuiz': self.quiz != 'disabled'}
        self.client = Client(self.root / 'ai-cache', consumer.verifier,
                             config={'model': 'test-model', 'judgeModel': 'test-model'}, transport=self.ai)
        speech = mock.Mock(provider='deepgram')
        speech.generate.side_effect = self.voix
        errors = []
        traiter = consumer._traiter

        def traitement():
            try:
                traiter()
            except Exception as error:
                errors.append(error)
                raise

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(consumer, '_traiter', side_effect=traitement))
            stack.enter_context(mock.patch('socket.socket.connect', side_effect=AssertionError('Réseau interdit')))
            stack.enter_context(mock.patch('subprocess.Popen', side_effect=AssertionError('Processus externe interdit')))
            stack.enter_context(mock.patch.object(discover_source, 'preparer', side_effect=self.source_media))
            stack.enter_context(mock.patch.object(discover_source, 'preparer_youtube', side_effect=self.source_media))
            stack.enter_context(mock.patch.object(discover_preparation, 'Client', return_value=self.client))
            stack.enter_context(mock.patch('discover_vocabulary.charger', return_value=set()))
            stack.enter_context(mock.patch('discover_speech.Session', return_value=speech))
            stack.enter_context(mock.patch('pipeline.duree_audio_secondes', return_value=10))
            stack.enter_context(mock.patch.object(discover_cible, 'requete', side_effect=self.worker))
            # Les exceptions sont capturées par la file : arrêter aussitôt pour éviter une attente/reprise réelle.
            stack.enter_context(mock.patch.object(consumer.stop, 'wait', return_value=True))
            consumer._executer()
        if errors:
            raise AssertionError('Préparation simulée interrompue') from errors[0]
        self.consumer = consumer
        self.costs = discover_costs.rapport(self.root, {})
        return self
