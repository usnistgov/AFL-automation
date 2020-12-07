from flask import Flask, render_template, request, jsonify

#authentication module
from flask_jwt_extended import JWTManager, jwt_required 
from flask_jwt_extended import create_access_token, get_jwt_identity

import datetime,requests,subprocess,shlex,os
import threading,queue,logging,json,pathlib,uuid

from logging.handlers import SMTPHandler
from logging import FileHandler

from NistoRoboto.APIServer.QueueDaemon import QueueDaemon
from NistoRoboto.APIServer.LoggerFilter import LoggerFilter

from NistoRoboto.shared.MutableQueue import MutableQueue

class APIServer:
    def __init__(self,name,experiment='Development',contact='tbm@nist.gov'):
        self.name = name
        self.experiment = experiment
        self.contact = contact

        self.logger_filter= LoggerFilter('get_queue','queue_state','driver_status')


        #allows the flask server to find the static and templates directories
        root_path = pathlib.Path(__file__).parent.absolute()
        self.app = Flask(name,root_path=root_path)

        self.queue_daemon = None
        self.app.config['JWT_SECRET_KEY'] = '03570' #hide the secret?
        self.app.config['JWT_ACCESS_TOKEN_EXPIRES'] = False
        self.jwt = JWTManager(self.app)

    def create_queue(self,driver):
        self.history = []
        self.task_queue = MutableQueue()
        self.driver     = driver
        self.driver.app = self.app
        self.queue_daemon = QueueDaemon(self.app,driver,self.task_queue,self.history)

    def reset_queue_daemon(self,driver=None):
        if driver is not None:
            self.driver=driver
        self.queue_daemon.terminate()
        self.create_queue(self.driver)
        return 'Success',200

    def run(self,**kwargs):
        if self.queue_daemon is None:
            raise ValueError('create_queue must be called before running server')
        self.app.run(**kwargs)

    def run_threaded(self,start_thread=True,**kwargs):
        if self.queue_daemon is None:
            raise ValueError('create_queue must be called before running server')

        thread = threading.Thread(target=self.app.run,daemon=True,kwargs=kwargs)
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
        self.app.add_url_rule('/driver_status','driver_status',self.driver_status,methods=['GET'])
        self.app.add_url_rule('/login','login',self.login,methods=['POST'])
        self.app.add_url_rule('/login_test','login_test',self.login_test,methods=['GET','POST'])
        self.app.add_url_rule('/reset_queue_daemon','reset_queue_daemon',self.reset_queue_daemon,methods=['POST'])

        self.app.before_first_request(self.init)

    def init_logging(self,toaddrs=None):
        self.app.logger.setLevel(level=logging.DEBUG)

        if toaddrs is not None:
            # setup error emails
            mail_handler = SMTPHandler(mailhost=('smtp.nist.gov',25),
                               fromaddr=f'{self.name}@pg93001.ncnr.nist.gov', 
                               toaddrs=toaddrs, 
                               subject='Driver Error')
            mail_handler.setLevel(logging.ERROR)
            self.app.logger.addHandler(mail_handler)


        file_handler = FileHandler(f'nistoroboto.{self.name}.log')
        file_handler.setFormatter(logging.Formatter(
                '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
                ))
        self.app.logger.addHandler(file_handler)
        logging.getLogger('werkzeug').addHandler(file_handler)


    def index(self):
        '''Live, status page of the robot'''
        self.app.logger.info('Serving index page')

        kw = {}
        kw['queue']       = self.get_queue()
        kw['contact']     = self.contact
        kw['experiment']  = self.experiment
        kw['queue_state'] = self.queue_state()
        kw['name']        = self.name
        kw['driver']    = self.queue_daemon.driver.name
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

    def driver_status(self):
        status = self.queue_daemon.driver.status()
        return jsonify(status),200

    def get_queue(self):
        output = [self.history,self.queue_daemon.running_task,list(self.task_queue.queue)]
        return jsonify(output),200

    @jwt_required
    def enqueue(self):
        task = request.json
        if 'queue_loc' in task:
            queue_loc = task['queue_loc']
            del task['queue_loc']
        else:
            #insert at back of queue
            queue_loc=self.task_queue.qsize()

        user = get_jwt_identity()
        self.app.logger.info(f'{user} enqueued {request.json}')
        package = {'task':task,'meta':{},'uuid':uuid.uuid4()}
        package['meta']['queued'] = datetime.datetime.now().strftime('%H:%M:%S')
        self.task_queue.put(package,queue_loc)
        return str(package['uuid']),200

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
        self.app.logger.info(f'Halting all drivers and stopping QueueDaemon')
        # ToDo....
        return 'Success',200

    def init(self):
        # this kills the default werkzeug webserver output
        # log = logging.getLogger('werkzeug')
        #log.disabled = True

        self.app.logger.info('Spawning Daemons')
        self.queue_daemon.start()

        return 'Success',200

    def login(self):
        if not request.is_json:
            return jsonify({"msg": "Missing JSON in request"}), 400
    
        username = request.json.get('username', None)
        if username is None:
            return jsonify({"msg": "Missing username parameter"}), 400

        password = request.json.get('password', None)
        if password is None:
            return jsonify({"msg": "Missing password parameter"}), 400
    
        if password != 'domo_arigato':
            return jsonify({"msg": "Bad password"}), 401
    
        # Identity can be any data that is json serializable
        #expires = datetime.timedelta(days=1)
        self.app.logger.info(f'Creating login token for user {username}')
        token = create_access_token(identity=username)#,expires=expires)
        return jsonify(token=token), 200
    
    @jwt_required
    def login_test(self):
        username = get_jwt_identity()
        self.app.logger.info(f'Login test for {username} successful')
        return 'Success',200



if __name__ =='__main__':

    from NistoRoboto.APIServer.DummyDriver import DummyDriver
    server = APIServer('TestServer')
    server.add_standard_routes()
    server.create_queue(DummyDriver())
    server.run(host='0.0.0.0',debug=True)
