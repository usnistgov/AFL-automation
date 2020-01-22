import requests,datetime

import queue
task_queue = queue.Queue()

from NistoRoboto.server.Server import Server
roboto_server = Server(task_queue)
roboto_server.start()# start server thread

from flask import Flask, render_template
from flask import request, jsonify, Markup
#app = Flask('NistoRoboto') #okay this breaks the templating apparently
app = Flask(__name__)

from flask_jwt_extended import (
    JWTManager, jwt_required, create_access_token,
    get_jwt_identity
)
# initialize auth module
# maybe hide the secret at some point?
app.config['JWT_SECRET_KEY'] = '03570'  
jwt = JWTManager(app)

@app.route('/')
def index():
    '''
    This should be a live, status page of the robo

    This page should include:
    - status/queue of robot
    - currently running command
    - loaded labeware
    - visualization of the deck


    - button should stop robot (hard halt)
    - robot should only accept commands if the door is closed
    - color of button should reflect state
    '''
    kw = {}
    kw['pipettes'] = roboto_server.protocol.loaded_instruments
    kw['labware']  = roboto_server.protocol.loaded_labwares

    queue_str  = '<ol>\n'
    for task in task_queue.queue:
        queue_str  += f'\t<li>{task}</li>\n'
    queue_str  += '</ol>\n'
    kw['queue'] = Markup(queue_str)

    #request image and save to static directory
    response = requests.post('http://localhost:31950/camera/picture')
    with open('static/deck.jpeg','wb') as f:
        f.write(response.content)

    return render_template('index.html',**kw)

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

    # Identity can be any data that is json serializable
    #expires = datetime.timedelta(days=1)
    token = create_access_token(identity=username)#,expires=expires)
    return jsonify(token=token), 200

@app.route('/enqueue',methods=['POST'])
@jwt_required
def enqueue():
    task_queue.put(request.json)
    return 'Success',200


if __name__ == '__main__':
    app.run(host='0.0.0.0',debug=True)
