from flask import Flask, render_template
from flask import request, jsonify, Markup

import datetime,requests

experiment = 'Development'
contactinfo = 'tbm@nist.gov'
#app = Flask('NistoRoboto') #okay this breaks the templating apparently
app = Flask(__name__)


import logging
app.logger.setLevel(level=logging.DEBUG)

import queue
task_queue = queue.Queue()

from NistoRoboto.server.RobotoDaemon import RobotoDaemon
roboto_daemon = RobotoDaemon(app,task_queue,debug_mode=True)
roboto_daemon.start()# start server thread

# initialize auth module
from flask_jwt_extended import JWTManager, jwt_required 
from flask_jwt_extended import create_access_token, get_jwt_identity
app.config['JWT_SECRET_KEY'] = '03570' #hide the secret?
jwt = JWTManager(app)

@app.route('/')
def index():
    '''Live, status page of the robot'''
    kw = {}
    kw['pipettes'] = roboto_daemon.protocol.protocol.loaded_instruments
    kw['labware']  = roboto_daemon.protocol.protocol.loaded_labwares

    kw['updatetime'] = _nbsp(datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
    kw['robotstatus'] = _nbsp(_queue_status(task_queue))
    kw['currentexperiment'] = _nbsp(experiment)
    kw['contactinfo'] = _nbsp(contactinfo)
    if roboto_daemon.debug_mode:
        kw['queuemode'] = 'DEBUG'
    else:
        kw['queuemode'] = 'ACTIVE'

    queue_str  = '<ol>\n'
    for task in task_queue.queue:
        queue_str  += f'\t<li>{task}</li>\n'
    queue_str  += '</ol>\n'
    kw['queue'] = Markup(queue_str)

    #request image and save to static directory

    # TO SET UP STREAM IN FUTURE:
    # ffmpeg -y -f video4linux2 -s 640x480 -i /dev/video0 'udp://239.0.0.1:1234?ttl=2'

    # this will UDP multicast stream to 239.0.0.1:1234, pick this stream up on control server and repackage it.
    
    response = requests.post('http://localhost:31950/camera/picture')
    with open('static/deck.jpeg','wb') as f:
        f.write(response.content)

    return render_template('index.html',**kw)

def _nbsp(instr):
    return Markup(instr.replace(' ','&nbsp;'))

@app.route('/login',methods=['GET','POST'])
def login():
    if not request.is_json:
        return jsonify({"msg": "Missing JSON in request"}), 400

    username = request.json.get('username', None)
    password = request.json.get('password', None)
    if not username:
        return jsonify({"msg": "Missing username parameter"}), 400
    if not password:
        return jsonify({"msg": "Missing password parameter"}), 400

    if password != 'domo_arigato':
        return jsonify({"msg": "Bad password"}), 401

    experiment = request.json.get('experiment',None)
    contactinfo = request.json.get('contactinfo',None)

    # Identity can be any data that is json serializable
    #expires = datetime.timedelta(days=1)
    app.logger.info(f'Creating login token for user {username}')
    token = create_access_token(identity=username)#,expires=expires)
    return jsonify(token=token), 200

def _queue_status(q):
    if q.empty():
        return "Idle"
    else:
        return f"Running, {q.qsize()} pending tasks."

@app.route('/enqueue',methods=['POST'])
@jwt_required
def enqueue():
    task_queue.put(request.json)
    return 'Success',200

@app.route('/login_test',methods=['POST'])
@jwt_required
def login_test():
    username = get_jwt_identity()
    app.logger.info(f'Login test for {username} successful')
    return 'Success',200


if __name__ == '__main__':
    app.run(host='0.0.0.0',debug=True)

