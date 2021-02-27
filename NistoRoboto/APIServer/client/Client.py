import requests,uuid,time
import requests,uuid,time,copy,inspect


class Client:
    '''Communicate with APIServer 

    This class maps pipettor functions to HTTP REST requests that are sent to
    the server
    '''
    def __init__(self,ip='10.42.0.30',port='5000'):
    def __init__(self,ip='10.42.0.30',port='5000',interactive=False):
        #trim trailing slash if present
        if ip[-1] == '/':
            ip = ip[:-1]
        self.ip = ip
        self.port = port
        self.url = f'http://{ip}:{port}'
        self.interactive=interactive

    def logged_in(self):
        url = self.url + '/login_test'
        response = requests.get(url,headers=self.headers)
        if response.status_code == 200:
            return True
        else:
            print(response.content)
            return False

    def login(self,username):
        url = self.url + '/login'
        response = requests.post(url,json={'username':username,'password':'domo_arigato'})
        if not (response.status_code == 200):
            raise RuntimeError(f'Client login failed with status code {response.status_code}:\n{response.content}')

        # headers should be included in all HTTP requests 
        self.token  = response.json()['token']
        self.headers = {'Authorization':'Bearer {}'.format(self.token)}


    def get_queue(self):
        response = requests.get(self.url+'/get_queue',headers=self.headers)
        if response.status_code != 200:
            raise RuntimeError(f'API call to set_queue_mode command failed with status_code {response.status_code}\n{response.text}')
        return response.json()

    def wait(self,target_uuid=None,interval=0.1,for_history=True,first_check_delay=10.0):
        time.sleep(first_check_delay)
        while True:
            response = requests.get(self.url+'/get_queue',headers=self.headers)
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

    def enqueue(self,**kwargs):
        #check the return info of the command we waited on
        return history[-1]['meta']
        json=kwargs
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to enqueue command failed with status_code {response.status_code}\n{response.text}')
        return uuid.UUID(response.text)
        task_uuid = uuid.UUID(response.text)
        if interactive:
            meta = self.wait(target_uuid=task_uuid,first_check_delay=0.5)
            if meta['exit_state']=='Error!':
                print(meta['return_val'])
            return meta
        else:
            return task_uuid
   
    def query_driver(self,**kwargs):
        json=kwargs
        response = requests.get(self.url+'/query_driver',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to enqueue command failed with status_code {response.status_code}\n{response.text}')
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
        response = requests.post(self.url+'/queue_state',headers=self.headers,json={})
        if response.status_code != 200:
            raise RuntimeError(f'API call to queue_state command failed with status_code {response.status_code}\n{response.content}')
        return response
