# coding: utf-8
from datetime import datetime
import json
import pprint
from time import sleep
from xml.etree.ElementTree import fromstring

from elasticsearch import Elasticsearch
from elasticsearch import helpers

import grequests
import requests

from xmljson import badgerfish as bf


NEXTBUS_API = ' http://webservices.nextbus.com/service/publicXMLFeed?command='
pp = pprint.PrettyPrinter(indent=2)


def get_interval(route):
    """
    Gets the interval for a specific route (with a specific
    service class and direction).
    """
    start, end = None, None
    first_block = route[0]['stop']
    for stop in first_block:
        if stop['$'] != '--':
            start = stop['$']
            break

    last_block = route[-1]['stop']
    for stop in reversed(last_block):
        if stop['$'] != '--':
            end = stop['$']
            break

    return start, end


def build_route_min_max(route):
    """
    For each route, this function tries to determine when does
    the route start operating and when does it stop.
    :type route: list
    :param route:
    """
    d = {'first': None, 'last': None}
    for r in route:
        start, end = get_interval(r['tr'])
        if not d['first']:
            d['first'] = start
        else:
            s = datetime.strptime(start, '%H:%M:%S').time()
            f = datetime.strptime(d['first'], '%H:%M:%S').time()
            if s < f:
                d['first'] = start

        if not d['last']:
            d['last'] = end
        else:
            f = datetime.strptime(d['first'], '%H:%M:%S').time()
            e = datetime.strptime(end, '%H:%M:%S').time()
            l = datetime.strptime(d['last'], '%H:%M:%S').time()
            if e > l or (e < l and e < f and l > f):
                d['last'] = end

    return d


def process_batch(batch):
    """
    :type batch: list
    :param batch:
    """
    res = grequests.map(batch)
    data = []
    for response in res:
        res_json = bf.data(fromstring(response.text))
        route = res_json['body']['route']
        if not isinstance(route, list):
            route = [route]

        d = build_route_min_max(route)
        d['route'] = route[0]['@tag']
        data.append({
            '_op_type': 'update',
            '_index': 'nextbus',
            '_type': 'route',
            '_id': d['route'],
            'doc': d,
            'doc_as_upsert': True
        })

    helpers.bulk(elas, data)
    print('[INFO] Added data to ElasticSearch: {}'.format(data))


def fetch_and_populate(es_client):
    # We first get all the routes from SF-Muni
    res = requests.get('{}routeList&a=sf-muni'.format(NEXTBUS_API)).text
    res_json = bf.data(fromstring(res))
    routes = [route['@tag'] for route in res_json['body']['route']]

    # Now we crawl over all the routes and fetch their schedules, in batches
    # of 5. Unfortunately, NextBus webservice stops being responsive after
    # a few calls. We retry processing each batch 3 times in case of failure.
    for i in range(0, (len(routes) // 10) * 10 + 1, 5):
        rs = [grequests.get('{}schedule&a=sf-muni&r={}'.format(NEXTBUS_API, r)) for r in routes[i:i+5]]
        limit, repeat = 4, True
        while repeat and limit > 1:
            try:
                process_batch(rs)
                repeat = False
            except:
                limit -= 1
                print('[ERROR] Problem processing the batch ({})'.format(limit))
                sleep(1 + 1 / limit)


if __name__ == '__main__':
    print('[INFO] Letting other services warm up...')
    sleep(5)

    elas = Elasticsearch(["elas"])

    while True:
        fetch_and_populate(elas)

        # We repopulate ElasticSearch every hour. Not sure
        # how necessary this is, depends on how frequently
        # the data in NextBus changes.
        sleep(3600)
