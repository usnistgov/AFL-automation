from flask import Flask, render_template, request, jsonify,send_file

from flask_cors import CORS

#authentication module
from flask_jwt_extended import (
    JWTManager, jwt_required, create_access_token,
    create_refresh_token,
    get_jwt_identity, set_access_cookies,
    set_refresh_cookies, unset_jwt_cookies
)



import datetime,requests,subprocess,shlex,os,time
import threading,queue,logging,json,pathlib,uuid

from logging.handlers import SMTPHandler
from logging import FileHandler

from NistoRoboto.APIServer.QueueDaemon import QueueDaemon
from NistoRoboto.APIServer.LoggerFilter import LoggerFilter

from NistoRoboto.shared.MutableQueue import MutableQueue
from NistoRoboto.shared.utilities import listify

import warnings

try:
#this import block is all for the web-ui unqueued rendering code
    import bokeh
    import bokeh.plotting
    from bokeh.resources import INLINE
    from bokeh.core.templates import JS_RESOURCES
    from bokeh.core.templates import CSS_RESOURCES
    from PIL import Image
    from matplotlib import cm
    import io
    import numpy as np
    from distutils.util import strtobool
except ImportError:
    warnings.warn('Plotting imports failed! Live data plotting will not work on this server.')

class APIServer:
    def __init__(self,name,experiment='Development',contact='tbm@nist.gov',index_template='index.html',plot_template='simple-bokeh.html'):
        self.name = name
        self.experiment = experiment
        self.contact = contact
        self.index_template = index_template
        self.plot_template = plot_template

        self.logger_filter= LoggerFilter('get_queue','queue_state','driver_status','get_server_time','get_info')

        #allows the flask server to find the static and templates directories
        root_path = pathlib.Path(__file__).parent.absolute()
        self.app = Flask(name,root_path=root_path)

        self.queue_daemon = None
        self.app.config['JWT_SECRET_KEY'] = '03570' #hide the secret?
        self.app.config['JWT_ACCESS_TOKEN_EXPIRES'] = False
        self.jwt = JWTManager(self.app)

        # CORS may have to come after JWTManager
        self.cors = CORS(self.app)


    def create_queue(self,driver):
        self.history = []
        self.task_queue = MutableQueue()
        self.driver     = driver
        self.driver.app = self.app
        self.queue_daemon = QueueDaemon(self.app,driver,self.task_queue,self.history)

        self.add_unqueued_routes()


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
        self.app.add_url_rule('/app','app',self.webapp)
        self.app.add_url_rule('/webapp','webapp',self.webapp)
        self.app.add_url_rule('/enqueue','enqueue',self.enqueue,methods=['POST'])
        self.app.add_url_rule('/query_driver','query_driver',self.query_driver,methods=['GET'])
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
        self.app.add_url_rule('/is_server_live','is_server_live',self.is_server_live,methods=['GET'])
        self.app.add_url_rule('/get_queued_commands','get_queued_commands',self.get_queued_commands,methods=['GET'])
        self.app.add_url_rule('/get_unqueued_commands','get_unqueued_commands',self.get_unqueued_commands,methods=['GET'])
        self.app.add_url_rule('/get_server_time','get_server_time',self.get_server_time,methods=['GET'])
        self.app.add_url_rule('/remove_item','remove_item',self.remove_item,methods=['POST'])
        self.app.add_url_rule('/move_item','move_item',self.move_item,methods=['POST'])
        self.app.add_url_rule('/get_info','get_info',self.get_info,methods=['GET'])
        self.app.add_url_rule('/reorder_queue','reorder_queue',self.reorder_queue,methods=['POST'])
        self.app.add_url_rule('/remove_items','remove_items',self.remove_items,methods=['POST'])
        self.app.add_url_rule('/get_quickbar','get_quickbar',self.get_quickbar,methods=['POST','GET'])
        self.app.before_first_request(self.init)

    def get_info(self):
        '''Live, status page of the robot'''
        #self.app.logger.error(print(self.get_queue()[0].json))
        kw = {}
        kw['queue']       = self.get_queue()[0].json
        kw['contact']     = self.contact
        kw['experiment']  = self.experiment
        kw['queue_state'] = self.queue_state()[0]
        kw['name']        = self.name
        kw['driver']    = self.queue_daemon.driver.name
        return jsonify(kw),200

    def get_quickbar(self):
        '''
        Return the functions, params, and defaults to be shown in this server's quickbar
        '''
        return jsonify(self.driver.quickbar.function_info),200

    def is_server_live(self):
        self.app.logger.debug("Server is live.")
        return 200

    def get_unqueued_commands(self):
        return jsonify(self.driver.unqueued.function_info),200

    def get_queued_commands(self):
        return jsonify(self.driver.queued.function_info),200

    def add_unqueued_routes(self):
        print('Adding unqueued routes')
        for fn in self.driver.unqueued.functions:
            route = '/' + fn
            name = fn
            kwarg_add = self.driver.unqueued.decorator_kwargs[fn]
            response_function = None
            response_function = lambda fn=fn,kwarg_add=kwarg_add: self.render_unqueued(getattr(self.driver,fn),kwarg_add)
            print(f'Adding route {route} for function named {name} with baked-in kwargs {kwarg_add}')
            self.app.add_url_rule(route,name,response_function,methods=['GET'])

    def query_driver(self):
        if request.json:
            task = request.json
        else:
            task = request.args

        self.app.logger.info(f'Request for {request.args}')
        if 'r' in task:
            if task['r'] in self.driver.unqueued.functions:
                return getattr(self.driver,task['r'])(**task),200
            else:
                return "No such task found as an unqueued function in driver"
        else:
            return "No task specified, add argument r=task to get result",404



    def init_logging(self,toaddrs=None):
        self.app.logger.setLevel(level=logging.DEBUG)

        if toaddrs is not None:
            # setup error emails
            mail_handler = SMTPHandler(mailhost=('smtp.nist.gov',25),
                               fromaddr=f'{self.name}@pg903001.ncnr.nist.gov',
                               toaddrs=toaddrs,
                               subject='Driver Error')
            mail_handler.setLevel(logging.ERROR)
            self.app.logger.addHandler(mail_handler)



        path = pathlib.Path.home() / '.nistoroboto'
        path.mkdir(exist_ok=True,parents=True)
        filepath = path / f'{self.name}.log'
        file_handler = FileHandler(filepath)
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
        return render_template(self.index_template,**kw),200

    def webapp(self):
        '''Live, status page of the robot'''
        self.app.logger.info('Serving WebApp')

        return render_template('webapp.html'),200

    def render_unqueued(self,func,kwargs_add,**kwargs):
        '''Convert an unqueued return item into web-suitable output'''
        self.app.logger.info(f'Serving unqueued function: {func.__name__} received with decorator kwargs {kwargs_add}')
        kwargs.update(kwargs_add)
        if request.json:
            kwargs.update(request.json)
        kwargs.update(request.args)
        render_hint = kwargs['render_hint'] if 'render_hint' in kwargs else None
        result = func(**kwargs)
        ##result = lambda: func(**kwargs)

        if render_hint is None: #try and infer what we should do based on the return type of func.
            res_probe = result[0] if type(result) == list else result
            if type(res_probe) == np.ndarray:
                if res_probe.ndim == 1:
                    render_hint = '1d_plot'
                if res_probe.ndim == 2:
                    render_hint = '2d_img'
                else:
                    #how do we support a 3d array?  throw up our hands.
                    render_hint = 'raw'
            else:
                #don't do complicated rendering
                render_hint='raw'
        if render_hint == '1d_plot':
            return self.send_1d_plot(result,**kwargs) #lambda:
        elif render_hint == '2d_img':
            return self.send_array_as_jpg(result,**kwargs) #lambda:
        elif render_hint == 'raw':
            if type(result) is np.ndarray:
                result = result.tolist()
            return jsonify(result)
        else:
            return "Error while rendering output",500

    def send_1d_plot(self,result,multi=False,**kwargs):
        if 'xlin' in kwargs:
            if type(kwargs['xlin']) is str:
                xlin = strtobool(kwargs['xlin'])
            else:
                xlin = kwargs['xlin']
            xmode = 'linear' if xlin else 'log'
        else:
            xmode = 'log'
        if 'ylin' in kwargs:
            if type(kwargs['ylin']) is str:
                ylin = strtobool(kwargs['ylin'])
            else:
                ylin = kwargs['ylin']
            ymode = 'linear' if ylin else 'log'
        else:
            ymode = 'log'


        TOOLS = 'pan,wheel_zoom,box_zoom,reset,save'

        title = kwargs['title'] if 'title' in kwargs else ''

        p = bokeh.plotting.figure(title=title,tools=TOOLS,x_axis_type=xmode,y_axis_type=ymode)
        p.xaxis.axis_label = kwargs['xlabel'] if 'xlabel' in kwargs else 'x'
        p.yaxis.axis_label = kwargs['ylabel'] if 'ylabel' in kwargs else 'y'

        if multi:
            for item in listify(result):
                p.scatter(item[0],item[1],marker='circle', size=2,
                    line_color='navy', fill_color='orange', alpha=0.5)
        else:
            p.scatter(result[0],result[1],marker='circle', size=2,
                    line_color='navy', fill_color='orange', alpha=0.5)
            if len(result)>2:
                errors = bokeh.models.Band(base=result[1],upper=result[1]+result[2],lower=result[1]-result[2], level='underlay',
                fill_alpha=1.0, line_width=1, line_color='black')
                p.add_layout(band)

        bokeh_js = JS_RESOURCES.render(
                js_raw = INLINE.js_raw,
                js_files = INLINE.js_files,
        )
        bokeh_css = CSS_RESOURCES.render(
                css_raw = INLINE.css_raw,
                css_files = INLINE.css_files,
        )
        script,div = bokeh.embed.components(p)
        # return render_template(self.plot_template,script=script,div=div,title=title,plot_resources=plot_resources)
        return render_template(self.plot_template,script=script,div=div,title=title,bokeh_css=bokeh_css,bokeh_js=bokeh_js)

    def send_array_as_jpg(self,array,log_image=False,max_val=None,fillna=0.0,**kwargs):
        #img = Image.fromarray(array.astype('uint8'))
        #self.app.logger.info(type(array))
        array = np.nan_to_num(array,nan=fillna)
        #self.app.logger.info(str(array))
        if type(log_image) is str:
            log_image = strtobool(log_image)
        if log_image:
            array = np.ma.log(array).filled(0)
        if max_val is None:
            self.app.logger.info(f'Serving image, max val = {np.amax(array)}, min val = {np.amin(array)}, total cts = {np.sum(array)}')
            max_val = np.amax(array)
        else:
            max_val = float(max_val)


        array = array/max_val
        img = Image.fromarray(np.uint8(cm.viridis(array)*255)).convert('RGB')
        # create file-object in memory
        file_object = io.BytesIO()

        # write PNG in file-object
        img.save(file_object, 'jpeg')

        # move to beginning of file so `send_file()` it will read from start
        file_object.seek(0)
        return send_file(file_object, mimetype='image/jpeg')

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

    @jwt_required()
    def enqueue(self):
        task = request.json
        if 'queue_loc' in task:
            queue_loc = task['queue_loc']
            del task['queue_loc']
        else:
            #insert at back of queue
            queue_loc=self.task_queue.qsize()

        if 'uuid' in task:
            task_uuid = task['uuid']
            del task['uuid']
        else:
            task_uuid = uuid.uuid4()
        
        user = get_jwt_identity()
        self.app.logger.info(f'{user} enqueued {request.json}')
        package = {'task':task,'meta':{},'uuid':task_uuid}
        package['meta']['queued'] = datetime.datetime.now().strftime('%H:%M:%S')
        self.task_queue.put(package,queue_loc)

        return str(package['uuid']),200

    @jwt_required()
    def reorder_queue(self):
        data = request.json
        prior_state = data['prior_state']
        reordered_queue = data['queue']
        matches = True
        
        print(prior_state)
        if prior_state != 'Paused':
            self.app.logger.info(f'Setting queue paused state to true')
            self.queue_daemon.paused = True
        
        temp_queue = list()
        for n in range(self.task_queue.qsize()):
            q_task = self.task_queue.queue[n] #server queue task
            task_found = False
            for i in range(len(reordered_queue)):
                rq_task = reordered_queue[i] #reordered queue task
                if rq_task['uuid'] == str(q_task['uuid']):
                    task_found = True
                    temp_queue.insert(i, q_task)
                    print('found', rq_task)
            if task_found == False:
                matches = False
                print('failed')
                return 'Failed',400
        if matches:
            print('matched')
            self.task_queue.queue = temp_queue
            print(self.task_queue.queue)
            
        if prior_state != 'Paused':
            self.app.logger.info(f'Setting queue paused state to false')
            self.queue_daemon.paused = False
        
        return 'Success',200
        
    @jwt_required()
    def remove_items(self):
        items = request.json
        for i in range(len(items)):
            print('remove', items[i])
            uuid = items[i]['uuid']
            self.task_queue.remove(self._uuid_to_qpos(uuid))
        return 'Success',200

    def _uuid_to_qpos(self,uuid):
        for idx,item in enumerate(list(self.task_queue.queue)):
            if str(item['uuid']) == uuid:
                pos = idx
                break
        return pos

    @jwt_required()
    def remove_item(self):
        uuid=request.json['uuid']
        self.task_queue.remove(self._uuid_to_qpos(uuid))
        return 'Success',200

    @jwt_required()
    def move_item(self):
        uuid = request.json['uuid']
        pos = request.json['pos']
        self.task_queue.move(self._uuid_to_qpos(uuid),new_index=pos)
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

        try:
            #sometimes the token comes as a bytestring, possible due to different versions of jwt
            token = token.decode('utf8')
        except AttributeError:
            pass
        return jsonify(token=token), 200

    def get_server_time(self):
        now = datetime.datetime.now().strftime('%H:%M:%S - %y/%m/%d')
        return now


    @jwt_required()
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
