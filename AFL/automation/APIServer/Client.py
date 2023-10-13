import requests,uuid,time,copy,inspect
from AFL.automation.shared import serialization
from AFL.automation.shared.ServerDiscovery import ServerDiscovery

class Client:
    '''Communicate with APIServer 

    This class provides an interface to generate HTTP REST requests that are sent to
    an APIServer, monitor the status of those requests, and retrieve the results of
    those requests.  It is intended to be used as a client to the APIServer class.
    '''
    def __init__(self,ip=None,port='5000',username=None,interactive=False):
        if ip is None:
            raise InputError('Must specify ip')
        
        #trim trailing slash if present
        if ip[-1] == '/':
            ip = ip[:-1]
        self.ip = ip
        self.port = port
        self.url = f'http://{ip}:{port}'
        self.interactive=interactive
        try:
            import AFL.automation.shared.widgetui
            import IPython
        except ImportError:
            pass
        else:
            #Client.ui = AFL.automation.shared.widgetui.client_construct_ui
            setattr(Client,'ui',AFL.automation.shared.widgetui.client_construct_ui)
        if username is not None:
            self.login(username)


    @classmethod
    def from_server_name(cls,server_name,**kwargs):
        sd = ServerDiscovery()
        address = ServerDiscovery.sa_discover_server_by_name(server_name)[0]
        (address,port) = address.split(':')
        return cls(ip=address,port=port,**kwargs)

    def logged_in(self):
        url = self.url + '/login_test'
        response = requests.get(url,headers=self.headers)
        if response.status_code == 200:
            return True
        else:
            print(response.content)
            return False

    def login(self,username,populate_commands=True):
        url = self.url + '/login'
        response = requests.post(url,json={'username':username,'password':'domo_arigato'})
        if not (response.status_code == 200):
            raise RuntimeError(f'Client login failed with status code {response.status_code}:\n{response.content}')

        # headers should be included in all HTTP requests 
        self.token  = response.json()['token']
        self.headers = {'Authorization':'Bearer {}'.format(self.token)}
        if populate_commands:
            self.get_queued_commmands()
            self.get_unqueued_commmands()

    def driver_status(self):
        response = requests.get(self.url+'/driver_status',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to driver_status command failed with status_code {response.status_code}\n{response.text}')
        return response.json()
    def get_queue(self):
        response = requests.get(self.url+'/get_queue',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to set_queue_mode command failed with status_code {response.status_code}\n{response.text}')
        return response.json()

    def wait(self,target_uuid=None,interval=0.1,for_history=True,first_check_delay=5.0):
        time.sleep(first_check_delay)
        while True:
            try:
                response = requests.get(self.url+'/get_queue',headers=self.headers,timeout=15)
            except (TimeoutError,requests.exceptions.ConnectionError) as e:
                continue
            history,running,queued = response.json()
            if target_uuid is not None:
                if for_history:
                    if any([str(task['uuid'])==str(target_uuid) for task in history]):
                        break
                else:
                    if not any([str(task['uuid'])==str(target_uuid) for task in running+queued]):
                        break

            else:
                if len(running+queued)==0:
                    break
            time.sleep(interval)

        #check the return info of the command we waited on
        return history[-1]['meta']

    def get_quickbar(self):
        response = requests.get(self.url+'/get_quickbar',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to get_queued_commands command failed with status_code {response.status_code}\n{response.text}')

        return response.json()

    def server_cmd(self,cmd,**kwargs):
        json=kwargs
        response = requests.get(self.url+'/'+cmd,headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to server command failed with status_code {response.status_code}\n{response.text}')
        return response.json()

    def enqueued_base(self,**kwargs):
        return self.enqueue(**kwargs)
    
    def unqueued_base(self,**kwargs):
        response = requests.get(self.url+'/'+kwargs['endpoint'],headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to set_queue_mode command failed with status_code {response.status_code}\n{response.text}')
        return response.json()

    def get_unqueued_commmands(self,inherit_commands=True):
        response = requests.get(self.url+'/get_unqueued_commands',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to get_queued_commands command failed with status_code {response.status_code}\n{response.text}')
            
        if inherit_commands:
            #XXX Need to find a cleaner way to do this. It works reasonbly
            #XXX well, but it doesn't support tab completions
            for function_name,info in response.json().items():
                parameters = []
                for parameter_name,default in info['kwargs']:
                    p = inspect.Parameter(parameter_name,inspect.Parameter.KEYWORD_ONLY,default=default)
                    parameters.append(p)
                function = lambda **kwargs: self.unqueued_base(endpoint=function_name,**kwargs)
                function.__name__ = function_name
                function.__doc__ = info['doc']
                function.__signature__ = inspect.signature(self.enqueued_base).replace(parameters=parameters)
                setattr(self,function_name,function)
                
        return response.json()
        
    def get_queued_commmands(self,inherit_commands=True):
        response = requests.get(self.url+'/get_queued_commands',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to get_queued_commands command failed with status_code {response.status_code}\n{response.text}')

        if inherit_commands:
            #XXX Need to find a cleaner way to do this. It works reasonbly
            #XXX well, but it doesn't support tab completions
            for function_name,info in response.json().items():
                parameters = []
                for parameter_name,default in info['kwargs']:
                    p = inspect.Parameter(parameter_name,inspect.Parameter.KEYWORD_ONLY,default=default)
                    parameters.append(p)
                function = lambda **kwargs: self.enqueued_base(task_name=function_name,**kwargs)
                function.__name__ = function_name
                function.__doc__ = info['doc']
                function.__signature__ = inspect.signature(self.enqueued_base).replace(parameters=parameters)
                setattr(self,function_name,function)

        return response.json()

    def enqueue(self,interactive=None,**kwargs):
        if interactive is None:
            interactive = self.interactive
        if 'params' in kwargs:
            additional_kwargs = kwargs['params']()
            del kwargs['params']
            kwargs.update(additional_kwargs)
        json=kwargs
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to enqueue command failed with status_code {response.status_code}\n{response.text}')
        task_uuid = uuid.UUID(response.text)
        if interactive:
            meta = self.wait(target_uuid=task_uuid,first_check_delay=0.5)
            if meta['exit_state']=='Error!':
                print(meta['return_val'])
            return meta
        else:
            return task_uuid

    def set_config(self,interactive=None,**kwargs):
        return self.enqueue(interactive=interactive,task_name='set_config',**kwargs)

    def get_config(self,name,print_console=True,interactive=None):
        if name == 'all':
            return self.enqueue(interactive=interactive,task_name='get_configs',print_console=print_console)
        else:
            return self.enqueue(interactive=interactive,task_name='get_config',name=name,print_console=print_console)
   

    def get_server_time(self):
        response = requests.get(self.url+'/get_server_time',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to enqueue command failed with status_code {response.status_code}\n{response.text}')
        return response.text
   
    def query_driver(self,**kwargs):
        json=kwargs
        response = requests.get(self.url+'/query_driver',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to query_driver command failed with status_code {response.status_code}\n{response.text}')
        return response.text

    def reset_queue_daemon(self):
        response = requests.post(self.url+'/reset_queue_daemon',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to reset_queue_daemon command failed with status_code {response.status_code}\n{response.text}')
        
    def pause(self,state):
        json={'state':state}
        response = requests.post(self.url+'/pause',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to pause command failed with status_code {response.status_code}\n{response.text}')
        
    def clear_queue(self):
        response = requests.post(self.url+'/clear_queue',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to clear_queue command failed with status_code {response.status_code}\n{response.text}')

    def clear_history(self):
        response = requests.post(self.url+'/clear_history',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to clear_history command failed with status_code {response.status_code}\n{response.text}')

    def debug(self,state):
        json={'state':state}
        response = requests.post(self.url+'/debug',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to debug command failed with status_code {response.status_code}\n{response.text}')

    def halt(self):
        response = requests.post(self.url+'/halt',headers=self.headers,json={})
        if response.status_code != 200:
            raise RuntimeError(f'API call to halt command failed with status_code {response.status_code}\n{response.content}')

    def queue_state(self):
        response = requests.get(self.url+'/queue_state',headers=self.headers,json={})
        if response.status_code != 200:
            raise RuntimeError(f'API call to queue_state command failed with status_code {response.status_code}\n{response.content}')
        return response
    
    
    def remove_item(self,uuid):
        response = requests.post(self.url+'/remove_item',headers=self.headers,json={'uuid':uuid})
        if response.status_code != 200:
            raise RuntimeError(f'API call to remove_item command failed with status_code {response.status_code}\n{response.content}')
        return response
    
    
    def move_item(self,uuid,pos):
        response = requests.post(self.url+'/move_item',headers=self.headers,json={'uuid':uuid,'pos':pos})
        if response.status_code != 200:
            raise RuntimeError(f'API call to move_item command failed with status_code {response.status_code}\n{response.content}')
        return response

    def set_driver_object(self,**kw):
        json = {}
        for name,value in kw.items():
            value = serialization.serialize(value)
            json[name] = value
        response = requests.post(self.url+'/set_driver_object',headers=self.headers,json=json)
        return response

    def get_driver_object(self,name):
        json = {'name':name}
        response = requests.get(self.url+'/get_driver_object',headers=self.headers,json=json)
        return serialization.deserialize(response.json()['obj'])
    
    def set_object(self,serialize=True,**kw):
        json = {}
        json['task_name'] = 'set_object'
        if serialize:
            json['serialized'] = True
            
        for name,value in kw.items():
            if serialize:
                value = serialization.serialize(value)
            json[name] = value
        self.enqueue(**json)
        
    def get_object(self,name,serialize=True):
        json = {}
        json['task_name']  = 'get_object'
        json['name']  = name
        json['interactive']  = True
        json['serialize']  = serialize
        retval = self.enqueue(**json)
        if serialize:
            obj = serialization.deserialize(retval['return_val'])
        else:
            obj = retval['return_val']
        return obj

    def __str__(self):
        if self.logged_in():
            return f'APIServer Client(ip={self.ip},port={self.port}), connected'
        else:
            return f'APIServer Client(ip={self.ip},port={self.port}), disconnected'