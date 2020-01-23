import requests

class Client:
    '''Communicate with NistoRoboto server on OT-2

    This class maps pipettor functions to HTTP REST requests that are sent to
    the NistoRoboto server
    '''
    def __init__(self,ip='10.42.0.30',port='5000'):
        #trim trailing slash if present
        if ip[-1] == '/':
            ip = ip[:-1]
        self.ip = ip
        self.port = port
        self.url = 'http://{ip}:{port}'

    def logged_in(self):
        url = self.url + '/login_test'
        response = requests.post(url,headers=self.headers)
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

    def set_queue_mode(self,debug_mode=True):
        json={'debug_mode':debug_mode}
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to set_queue_mode command failed with status_code {response.status_code}\n{response.text}')

    def transfer(self,mount,source,dest,volume):
        '''Transfer fluid from one location to another

        Arguments
        ---------
        mount: str ('left' or 'right')
            Mount location of pipette to be used

        source: str or list of str
            Source wells to transfer from. Wells should be specified as three
            character strings with the first character being the slot number.

        dest: str or list of str
            Destination wells to transfer from. Wells should be specified as
            three character strings with the first character being the slot
            number.

        volume: float
            volume of fluid to transfer in microliters

        '''
        json = {}
        json['type']  = 'transfer'
        json['mount']  = mount
        json['source'] = source
        json['dest']   = dest
        json['volume'] = volume
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to transfer command failed with status_code {response.status_code}\n{response.content}')
