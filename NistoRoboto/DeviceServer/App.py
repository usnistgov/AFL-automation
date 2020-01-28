from flask import Flask, render_template
from flask import request, jsonify, Markup

import datetime,requests, subprocess,shlex,os

import threading,queue,logging

class DeviceServer:
    def __init__(self,name):
        self.task_queue = queue.Queue()
        self.app = Flask(name)

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
        self.app.add_url_rule('/get_queue','get_queue',self.get_queue,methods=['GET'])
        self.app.before_first_request(self.init)

    def index(self):
        '''Live, status page of the robot'''
        self.app.logger.info('Serving indexes')

        kw = {}
        kw['queue'] = self.get_queue()
        return render_template('index.html',**kw),200

    def get_queue(self):
        return jsonify(list(self.task_queue.queue)),200

    def enqueue(self):
        self.task_queue.put(request.json)
        return 'Success',200

    def clear_queue(self):
        self.task_queue.queue.clear()
        return 'Success',200
    
    def init(self):
        # from flask import current_app as app
        self.app.logger.info('Spawning Daemons')
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

