from flask import Flask, render_template
from flask import request, jsonify, Markup

import datetime,requests, subprocess,shlex,os

import threading,queue,logging,json

from NistoRoboto.DeviceServer.QueueDaemon import QueueDaemon

class DeviceServer:
    def __init__(self,name,experiment='Development',contact='tbm@nist.gov'):
        self.name = name
        self.experiment = experiment
        self.contact = contact

        self.app = Flask(name)
        self.queue_daemon = None

    def create_queue(self,protocol):
        self.history = []
        self.task_queue = queue.Queue()
        self.protocol = protocol
        self.protocol.app = self.app
        self.queue_daemon = QueueDaemon(self.app,protocol,self.task_queue,self.history)

    def run(self,**kwargs):
        if self.queue_daemon is None:
            raise ValueError('create_queue must be called before running server')
        self.app.run(**kwargs)

    def run_threaded(self,start_thread=True,**kwargs):
        if self.queue_daemon is None:
            raise ValueError('create_queue must be called before running server')

        thread = threading.Thread(target=self.app.run,kwargs=kwargs)
        if start_thread:
            thread.start()
        else:
            return thread

    def add_standard_routes(self):
        self.app.add_url_rule('/','index',self.index)
        self.app.add_url_rule('/enqueue','enqueue',self.enqueue,methods=['POST'])
        self.app.add_url_rule('/clear_queue','clear_queue',self.clear_queue,methods=['POST'])
        self.app.add_url_rule('/clear_history','clear_history',self.clear_history,methods=['POST'])
        self.app.add_url_rule('/debug','debug',self.debug,methods=['POST'])
        self.app.add_url_rule('/pause','pause',self.pause,methods=['POST'])
        self.app.add_url_rule('/halt','halt',self.halt,methods=['POST'])
        self.app.add_url_rule('/get_queue','get_queue',self.get_queue,methods=['GET'])
        self.app.add_url_rule('/queue_state','queue_state',self.queue_state,methods=['GET'])
        self.app.add_url_rule('/protocol_status','protocol_status',self.protocol_status,methods=['GET'])
        self.app.before_first_request(self.init)

        self.app.logger.setLevel(level=logging.DEBUG)

    def index(self):
        '''Live, status page of the robot'''
        self.app.logger.info('Serving index page')

        kw = {}
        kw['queue']       = self.get_queue()
        kw['contact']     = self.contact
        kw['experiment']  = self.experiment
        kw['queue_state'] = self.queue_state()
        kw['name']        = self.name
        kw['protocol']    = self.queue_daemon.protocol.name
        return render_template('index.html',**kw),200

    def queue_state(self):
        if self.queue_daemon.paused:
            state = 'Paused'
        elif self.queue_daemon.debug:
            state = 'Debug'
        elif self.queue_daemon.busy:
            state = 'Active'
        else:
            state = 'Ready'
        return state,200

    def protocol_status(self):
        status = self.queue_daemon.protocol.status()
        return jsonify(status),200

    def get_queue(self):
        output = [self.history,list(self.task_queue.queue)]
        return jsonify(output),200

    def enqueue(self):
        task = request.json
        package = {'task':task,'meta':{}}
        package['meta']['queued'] = datetime.datetime.now().strftime('%H:%M:%S')
        self.task_queue.put(package)
        return 'Success',200

    def clear_queue(self):
        self.task_queue.queue.clear()
        return 'Success',200

    def clear_history(self):
        del self.history[:]
        return 'Success',200

    def debug(self):
        state = request.json['state']
        self.app.logger.info(f'Setting queue debug state to {state}')
        self.queue_daemon.debug = state
        return 'Success',200

    def pause(self):
        state = request.json['state']
        self.app.logger.info(f'Setting queue paused state to {state}')
        self.queue_daemon.paused = state
        return 'Success',200

    def halt(self):
        self.app.logger.info(f'Halting all protocols and stopping QueueDaemon')
        # ToDo....
        return 'Success',200

    def init(self):
        # this kills the default werkzeug webserver output
        # log = logging.getLogger('werkzeug')
        #log.disabled = True

        self.app.logger.info('Spawning Daemons')
        self.queue_daemon.start()
        return 'Success',200

class Filter(object):
    def __init__(self, *filters):
        from werkzeug import serving

        self.filters = filters
        self._log_request = serving.WSGIRequestHandler.log_request

        parent = self

        def log_request(self, *args, **kwargs):
            if any(filter in self.requestline for filter in parent.filters):
                return

            parent._log_request(self, *args, **kwargs)

        serving.WSGIRequestHandler.log_request = log_request

if __name__ =='__main__':

    filter = Filter('get_queue','queue_state','protocol_status')
    

    from NistoRoboto.DeviceServer.DummyProtocol import DummyProtocol
    server = DeviceServer('TestServer')
    protocol = DummyProtocol()
    server.add_standard_routes()
    server.create_queue(protocol)
    server.run(debug=True)

