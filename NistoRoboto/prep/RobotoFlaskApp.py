from flask import Flask, render_template
from flask import request, jsonify
import requests

from flask_jwt_extended import (
    JWTManager, jwt_required, create_access_token,
    get_jwt_identity
)

import NistoRoboto.RobotoFlaskKey
def key_is_valid(key):
    if key == NistoRoboto.RobotoFlaskKey.__flaskkey__:
        return True
    else:
        return False

from RobotoServer import RobotoServer
roboto_server = RobotoServer()

app = Flask(__name__)

# maybe hide this at some point?
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
    '''
    kw = {}
    kw['pipettes'] = None#roboto_server.protocol.loaded_pipettes
    kw['labware']  = None#roboto_server.protocol.loaded_labware

    #request image and save to static directory
    #reply = requests.post('http://localhost:31950/camer/picture')

    return render_template('index.html',**kw)

@app.route('/login',methods=['POST'])
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
    token = create_access_token(identity=username)
    return jsonify(token=token), 200


@app.route('/transfer',methods=['POST'])
@jwt_required
def transfer():
    roboto_server.transfer(**request.json)
    return 'Success',200


if __name__ == '__main__':
    app.run(debug=True)
