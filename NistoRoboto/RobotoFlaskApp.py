from flask import Flask
from flask import request, jsonify


import NistoRoboto.RobotoFlaskKey
def key_is_valid(key):
    if key == NistoRoboto.RobotoFlaskKey.__flaskkey__:
        return True
    else:
        return False

from RobotoServer import RobotoServer
roboto_server = RobotoServer()

app = Flask(__name__)

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
    return 'Cool status and visualizations to come...'

@app.route('/transfer',methods=['POST'])
def transfer():
    if not (('key' in request.json) and key_is_valid(request.json['key'])):
        print('Basic server key-check failed')
        return 'Failed'
    roboto_server.transfer(**request.json)
    return 'Success'



if __name__ == '__main__':
    app.run(debug=True)
