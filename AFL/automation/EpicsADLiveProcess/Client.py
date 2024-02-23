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
        self.url = f'http://{ip}:{port}'

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

    def transfer(self,source,dest,volume,source_loc=None,dest_loc=None):
        '''Transfer fluid from one location to another

        Arguments
        ---------
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
        json['source'] = source
        json['dest']   = dest
        json['volume'] = volume
        if source_loc is not None:
            json['source_loc'] = source_loc
        if dest_loc is not None:
            json['dest_loc'] = dest_loc
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to transfer command failed with status_code {response.status_code}\n{response.content}')

    def load_labware(self,name,slot):
        json = {}
        json['type']  = 'load_labware'
        json['name'] = name
        json['slot'] = slot
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to load_labware command failed with status_code {response.status_code}\n{response.content}')

    def load_instrument(self,name,mount,tip_rack_slots):
        json = {}
        json['type']  = 'load_instrument'
        json['name'] = name
        json['mount'] = mount
        json['tip_rack_slots'] = tip_rack_slots
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to load_instrument command failed with status_code {response.status_code}\n{response.content}')

    def reset(self):
        json = {}
        json['type']  = 'reset'
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to reset command failed with status_code {response.status_code}\n{response.content}')

    def home(self):
        json = {}
        json['type']  = 'home'
        response = requests.post(self.url+'/enqueue',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to home command failed with status_code {response.status_code}\n{response.content}')

    def halt(self):
        response = requests.post(self.url+'/halt',headers=self.headers,json={})
        if response.status_code != 200:
            raise RuntimeError(f'API call to halt command failed with status_code {response.status_code}\n{response.content}')
