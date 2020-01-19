import requests

class Client:
    '''Communicate with NistoRoboto server on OT-2

    This class maps pipettor functions to HTTP REST requests that are sent to
    the NistoRoboto server
    '''
    def __init__(self,url = 'http://10.42.0.31:5000/'):
        self.url = url

    def login(self,username):
        response = requests.post(self.url+'/login',json={'username':username,'password':'domo_arigato'})
        if not (response.status_code == 200):
            raise RuntimeError(f'Client login failed with status code {response.status_code}')

        # headers should be included in all HTTP requests 
        self.token  = response.json()['token']
        self.headers = {'Authorization':'Bearer {}'.format(self.token)}

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
        json['mount']  = mount
        json['source'] = source
        json['dest']   = dest
        json['volume'] = volume
        jsonsponse = requests.post(self.url+'/transfer',headers=self.headers,json=json)
        if response.status_code != 200:
            raise RuntimeError(f'API call to transfer command failed with status_code {response.status_code}')
