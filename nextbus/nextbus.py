# coding: utf-8
from collections import OrderedDict
import configparser
import datetime as dt
import re
from urllib.parse import urlencode
from xml.etree.ElementTree import fromstring

from elasticsearch import Elasticsearch

from flask import Flask, make_response, request
from flask_restful import Api, Resource

from redis import StrictRedis

import requests

from xmljson import badgerfish as bf


#;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
# Helper functions
def load_config():
    """
    :rtype: configparser.ConfigParser
    """
    parser = configparser.ConfigParser()
    parser.read('nextbus.cfg')
    return parser

def to_format(xml_str, f='json'):
    """
    Converts an XML string into a JSON response or
    a proper XML response.
    :type xml_str : str
    :param xml_str:
    :type f: str
    :param f: Destination format (json or xml)
    :returns: A Python object or a Flask Response object.
    """
    if f == 'json':
        # Flask-RESTful by default sets content-type to 
        # JSON, so no need to build a response object
        return bf.data(fromstring(xml_str))
    elif f == 'xml':
        # A little workaround for a content type other than
        # JSON.
        response = make_response(xml_str)
        response.headers['content-type'] = 'application/xml'
        return response
    else:
        raise Exception('Unknown format')


#;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
# Globals
APP = Flask(__name__)
API = Api(APP)
CONFIG = load_config()['default']
REDIS_CLI = StrictRedis.from_url(
    CONFIG['redis_url'], decode_responses=True
)
ELASTICSEARCH = Elasticsearch(CONFIG['elasticsearch'])

#;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
# Request Handlers (Flask stuff)


class NextBusDefault(Resource):
    """
    This class is responsible for exposing all the endpoints
    in the NextBus API.
    """
    def get(self):
        n1 = dt.datetime.now().microsecond
        response_format = request.args.get('format', 'json').lower()

        endpoint = request.path.split('/')[-1]  # e.g. routeList
        nextbus_req = endpoint
        if len(request.args) > 0:
            # Ensure that the query params are sorted, since the entire URI is
            # used as a Redis key.
            args = OrderedDict(sorted(request.args.items(), key=lambda t: t[0]))
            nextbus_req = re.sub(
                r'(&?format=\w+)', '', endpoint + '&' + urlencode(args)
            )

        event_id = REDIS_CLI.incr('event_id')

        # Does the result exist in cache?
        res = REDIS_CLI.get(nextbus_req)
        if not res:
            res = requests.get(CONFIG['nextbus_api'] + nextbus_req).text
            cache = True
        else:
            cache = False

        # Increase hits on the endpoint
        n2 = dt.datetime.now().microsecond
        pipe = REDIS_CLI.pipeline(True)
        if cache:
            pipe.set(nextbus_req, res)
            # No need for setex, this is already a transaction.
            # Actually setex here would break things.
            pipe.expire(nextbus_req, 30)
        pipe.hincrby('total_queries', endpoint, 1)
        pipe.zadd(
            'slow_requests',
            **{'{}:{}'.format(endpoint, event_id): abs((n2 - n1) / 1e3)}
        )
        pipe.execute()

        return to_format(res, response_format)


class NextBusNotRunning(Resource):
    """
    Class that handles requests for retrieve routes that
    don't run at a certain time. It expects the following
    parameters:
        - t: this is mandatory. It should be a timestamp in
             the format HHMMSS
        - page: this is optional. Should be an integers. Each
                page holds at most 10 routes.
    """
    def get(self):
        t = request.args.get('t', None)
        if not t:
            return {
                'error': 'Mandatory parameter <t> is missing.'
            }

        t = request.args['t']
        page = request.args.get('page', 0)
        res = ELASTICSEARCH.search(
            index='nextbus',
            doc_type='route',
            body={
                'from': int(page) * 10,
                'size': 10,
                'query': {
                    'bool': {
                        'must': [
                            {'range': {'first': {'gte': t}}},
                            {'range': {'last': {'lte': t}}}
                        ]
                    }
                }
            }
        )

        total = res['hits']['total']
        return {
            'pages': total // 10 + int(total % 10 != 0),
            'routes': [route['_id'] for route in res['hits']['hits']]
        }


class NextBusTotalQueries(Resource):
    """
    Class that handles requests for total queries to an
    endpoint.
    """
    def get(self, endpoint):
        total_queries = REDIS_CLI.hget('total_queries', endpoint)

        return {'total_queries': int(total_queries) if total_queries else 0}


class NextBusSlowRequests(Resource):
    """
    Class than handles requests for slow requests.
    """
    def get(self):
        slow_requests = REDIS_CLI.zrange(
            'slow_requests', 0, -1, desc=True, withscores=True
        )

        return slow_requests


if __name__ == '__main__':
    API.add_resource(
        NextBusDefault,
        '/nextbus/agencyList',
        '/nextbus/routeList',
        '/nextbus/routeConfig',
        '/nextbus/predictions',
        '/nextbus/predictionsForMultiStops',
        '/nextbus/schedule',
        '/nextbus/messages',
        '/nextbus/vehicleLocations'
    )
    API.add_resource(
        NextBusNotRunning,
        '/nextbus/notRunning'
    )
    API.add_resource(
        NextBusTotalQueries,
        '/nextbus/total_queries/<string:endpoint>'
    )
    API.add_resource(
        NextBusSlowRequests,
        '/nextbus/slow_requests'
    )
    APP.run(host='0.0.0.0', debug=True)

