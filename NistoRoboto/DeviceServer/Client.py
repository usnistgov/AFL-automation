import requests

class Client:
    '''Communicate with DeviceServer 

    This class maps pipettor functions to HTTP REST requests that are sent to
    the server
    '''
    def __init__(self,ip='10.42.0.30',port='5000'):
        #trim trailing slash if present
        if ip[-1] == '/':
            ip = ip[:-1]
        self.ip = ip
        self.port = port
        self.url = f'http://{ip}:{port}'

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

    def enqueue(self,**kwargs):
        json=kwargs
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to set_queue_mode command failed with status_code {response.status_code}\n{response.text}')
        
    def pause(self,state):
        json={'state':state}
        response = requests.post(self.url+'/pause',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to set_queue_mode command failed with status_code {response.status_code}\n{response.text}')

    def debug_mode(self,state):
        json={'state':state}
        response = requests.post(self.url+'/debug_mode',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to set_queue_mode command failed with status_code {response.status_code}\n{response.text}')

    def halt(self):
        response = requests.post(self.url+'/halt',headers=self.headers,json={})
        if response.status_code != 200:
            raise RuntimeError(f'API call to halt command failed with status_code {response.status_code}\n{response.content}')

    def queue_state(self):
        response = requests.post(self.url+'/queue_state',headers=self.headers,json={})
        if response.status_code != 200:
            raise RuntimeError(f'API call to queue_state command failed with status_code {response.status_code}\n{response.content}')
        return response
