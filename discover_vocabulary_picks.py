"""Synchronisation explicite des sélections, sans génération ni stockage de secret."""
import argparse
from urllib.parse import urlencode

import discover_cible
import discover_englishfluency


def cible(config):
    if config.get('englishFluency'):
        return discover_englishfluency.destination(config)
    import bundles
    settings, error = bundles.charger_config_import()
    if error:
        raise ValueError('Configurer les accès EnglishFluency existants.')
    return discover_englishfluency.destination({'englishFluency': settings})


def liste(config, transport=discover_cible.requete):
    return transport(config, 'GET', '/atelier/vocabulary/picks?limit=50')


def synchroniser(config, transport=discover_cible.requete,
                 ef_transport=discover_englishfluency.requete, destination=None):
    target = destination or cible(config)
    report = {'sent': 0, 'already_known': 0, 'failed': 0, 'unacknowledged': 0}
    # Parcourir tous les états une seule fois évite de reprendre un échec du même lot.
    after = 0
    while True:
        page = transport(config, 'GET', '/atelier/vocabulary/picks?' + urlencode({'after': after, 'limit': 50}))
        for pick in page['picks']:
            if pick['status'] not in ('pending', 'failed'):
                continue
            payload = {key: pick[key] for key in ('word', 'sentence', 'contentId', 'publicationId',
                                                  'variantKey', 'segmentIndex', 'language')}
            payload.update(sourceId='discover:' + pick['id'], profileId=target['profileId'])
            try:
                result = ef_transport(target, '/words/picks', data=payload)
                if (result.get('ok') is not True or result.get('status') not in ('sent', 'already_known')
                        or not isinstance(result.get('wordId'), str) or not 0 < len(result['wordId']) <= 200):
                    raise ValueError('Réponse EnglishFluency invalide.')
                ack = {'status': result['status'], 'wordId': result['wordId']}
            except Exception:
                # Aucun corps distant ni secret dans le rapport ou le Worker.
                ack = {'status': 'failed'}
            try:
                transport(config, 'POST', '/atelier/vocabulary/picks/' + pick['id'] + '/result', ack)
                report[ack['status']] += 1
            except Exception:
                report['unacknowledged'] += 1
        after = page.get('nextAfter')
        if after is None:
            return report


def main():
    parser = argparse.ArgumentParser(description='Synchroniser les mots Discover vers EnglishFluency')
    parser.parse_args()
    print(synchroniser(discover_cible.charger_config()))


if __name__ == '__main__':
    main()
