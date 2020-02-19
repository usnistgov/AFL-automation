from flask import Flask, render_template
from flask import request, jsonify, Markup, send_file

from PIL import Image
import datetime,requests, subprocess,shlex,os,json,io,bokeh,pyFAI
import numpy as np
from distutils.util import strtobool
import bokeh.plotting,bokeh.models,pyFAI.azimuthalIntegrator
from AreaDetectorLive import AreaDetectorLive

#app = Flask('NistoRoboto') #okay this breaks the templating apparently
app = Flask(__name__)
app.config['ENV'] = 'development'
experiment = 'Development'
contactinfo = 'pab2@nist.gov'
# app.config['ENV'] = 'production'

# initialize auth module
from flask_jwt_extended import JWTManager, jwt_required 
from flask_jwt_extended import create_access_token, get_jwt_identity
app.config['JWT_SECRET_KEY'] = '03570' #hide the secret?
jwt = JWTManager(app)

import logging
app.logger.setLevel(level=logging.DEBUG)


# this is necessary to use the default debug reloading functionality 
if app.config['ENV']=='production' or os.environ.get("WERKZEUG_RUN_MAIN") =='true':
    #import queue
    results = []
    

    from EpicsADLiveProcessDaemon import EpicsADLiveProcessDaemon
    EADLP_daemon = EpicsADLiveProcessDaemon(app,results)
    EADLP_daemon.start()# start server thread

@app.route('/')
def index():
    '''Live, status page of the robot'''
    kw = status_dict()

    return render_template('index.html',**kw),200

@app.route('/results')
def results():
    response = "<ul>"
    for num,res in enumerate(EADLP_daemon.results):
        response += f'<li>#{num}  |  {res[0]}  | exp {res[1]} | '
        response += f'<a href="raw_image?n={num}&log=0" target="_blank">raw img</a>  |'
        response += f'<a href="unwrapped_image?n={num}&log=0" target="_blank">unwrapped img</a>  |'
        response += f'<a href="1d_plot?n={num}" target="_blank">reduced data</a></li>'
    response += "</ul>"
    return Markup(response)

@app.route('/raw_image',methods=['GET'])
def raw_image():
    itemnum = int(request.args['n'])
    if 'log' in request.args:
        log_image = strtobool(request.args['log'])
    else:
        log_image = True
    # convert numpy array to PIL Image
    npa = EADLP_daemon.results[itemnum][2]
    return send_array_as_jpg(npa,log_image=log_image)

@app.route('/unwrapped_image',methods=['GET'])
def unwrapped_image():
    itemnum = int(request.args['n'])
    if 'log' in request.args:
        log_image = strtobool(request.args['log'])
    else:
        log_image = True
    # convert numpy array to PIL Image
    npa = EADLP_daemon.results[itemnum][4].intensity

    return send_array_as_jpg(npa,log_image=log_image)

def send_array_as_jpg(array,log_image=False):
    if(log_image):
        array = np.log(array)
    img = Image.fromarray(array.astype('uint8'))

    # create file-object in memory
    file_object = io.BytesIO()

    # write PNG in file-object
    img.save(file_object, 'jpeg')

    # move to beginning of file so `send_file()` it will read from start    
    file_object.seek(0)

    return send_file(file_object, mimetype='image/jpeg')

@app.route('/1d_plot',methods=['GET'])
def oned_plot():
    items = request.args['n'].split(",")
    if 'xlin' in request.args:
        xlin = strtobool(request.args['xlin'])
        xmode = 'linear' if xlin else 'log'
    else:
        xmode = 'log'
    if 'ylin' in request.args:
        ylin = strtobool(request.args['ylin'])
        ymode = 'linear' if xlin else 'log'
    else:
        ymode = 'log'
    

    TOOLS = 'pan,wheel_zoom,box_zoom,reset,save'
    title = EADLP_daemon.results[int(items[0])][0]
    p = bokeh.plotting.figure(title=title,tools=TOOLS,x_axis_type=xmode,y_axis_type=ymode)
    p.xaxis.axis_label = 'q (A^-1)'
    p.yaxis.axis_label = 'Intensity (AU)'
    for item in items:
        res = EADLP_daemon.results[int(item)][3]
        p.scatter(res[0],res[1],marker='circle', size=2,
              line_color='navy', fill_color='orange', alpha=0.5)

    #errors = bokeh.models.Band(base=res[1],upper=res[1]+res[2],lower=res[1]-res[2], level='underlay',
    #        fill_alpha=1.0, line_width=1, line_color='black')
    #p.add_layout(band)
    script,div = bokeh.embed.components(p)
    return render_template('simple-bokeh.html',script=script,div=div,title=title)

@app.route('/reconfig_integrator',methods=['POST'])
def reconfig_integrator():
    poni1 = request.args['poni1']
    poni2 = request.args['poni2']
    rot1 = request.args['rot1']
    rot2 = request.args['rot2']
    rot3 = request.args['rot3']
    distance = request.args['distance']
    wavelength = request.args['wavelength']
    det_type = request.args['det_type']
    pixel1 = request.args['pixel1']
    pixel2 = request.args['pixel2']

    npts = request.args['npts']

    #sanity check for integrator integrity goes here...
    
    if(det_type != ''):
        EADLP_daemon.detector = pyFAI.detector_factory(name=det_type)
    else:
        EADLP_daemon.detector = pyFAI.detector_factory()

    EADLP_daemon.integrator = pyFAI.azimuthalIntegrator.AzimuthalIntegrator(detector = EADLP_daemon.detector,
        wavelength = wavelength,poni1 = poni1, poni2 = poni2, rot1 = rot1, rot2 = rot2,
        rot3 = rot3, distance = distance)

    EADLP_daemon.reduceDaemon.npts = npts

@app.route('/reconfig_detector',methods=['POST'])
def reconfig_detector():
    basepv= request.args['basepv']
    if 'cam' in request.args:
        cam = request.args['cam']
    else:
        cam = "cam1:"
    if 'filewriter' in request.args:
        filewriter = request.args['filewriter']
    else:
        filewriter="TIFF1:"
    if 'image' in request.args:
        image = request.args['image']
    else:
        image="image1:"

    EADLP_daemon.collateDaemon.detector = AreaDetectorLive(basepv = basepv,cam=cam,filewriter=filewriter,image=image)

    return 'Success',200


@app.route('/login_test',methods=['POST'])
@jwt_required
def login_test():
    username = get_jwt_identity()
    app.logger.info(f'Login test for {username} successful')
    return 'Success',200

if __name__ == '__main__':
    if app.config['ENV'] == 'development':
        debug = True
    else:
        debug = False
    app.run(host='0.0.0.0',debug=debug)

