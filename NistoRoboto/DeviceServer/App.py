from flask import Flask, render_template
from flask import request, jsonify, Markup

import datetime,requests, subprocess,shlex,os

import threading,queue,logging

from NistoRoboto.DeviceServer.QueueDaemon import QueueDaemon

class DeviceServer:
    def __init__(self,name,experiment='Development',contact='tbm@nist.gov'):
        self.history = []
        self.task_queue = queue.Queue()
        self.app = Flask(name)
        self.queue_daemon = QueueDaemon(self.app,self.task_queue,self.history)
        self.experiment = experiment
        self.contact = contact

    def run(self,**kwargs):
        self.app.run(**kwargs)

    def run_threaded(self,start_thread=True,**kwargs):
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
        self.app.before_first_request(self.init)

    def index(self):
        '''Live, status page of the robot'''
        self.app.logger.info('Serving index page')

        kw = {}
        kw['queue'] = self.get_queue()
        kw['contact'] = self.contact
        kw['experiment'] = self.experiment
        if self.queue_daemon.debug:
            kw['queue_state'] = 'Debug'
        elif self.queue_daemon.paused:
            kw['queue_state'] = 'Paused'
        else:
            kw['queue_state'] = 'Active'
        return render_template('index.html',**kw),200

    def get_queue(self):
        output = [self.history,list(self.task_queue.queue)]
        return jsonify(output),200

    def enqueue(self):
        task = request.json
        package = {'task':task,'meta':{}}
        package['meta']['queued'] = datetime.datetime.now().strftime('%H:%M')
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

# class QueueFilter(logging.Filter):  
#     def filter(self, record):  
#         return "get_queue" not in record.getMessage() 
# 
# for handler in logging.root.handlers:  
#         handler.addFilter(QueueFilter())

if __name__ =='__main__':

    server = DeviceServer('TestServer')
    server.add_standard_routes()
    server.run(debug=True)

