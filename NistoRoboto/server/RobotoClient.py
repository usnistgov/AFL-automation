import requests

class RobotoClient:
    def __init__(self,url = 'http://10.42.0.31:5000/'):
        self.url = url

    def login(self,username):
        kw = {}
        kw['username'] = username
        kw['password'] = 'domo_arigato'
        reply = requests.post(self.url+'/login',json=kw)
        if not (reply.status_code == 200):
            raise RuntimeError(f'RobotoClient Login failed with error code {reply.status_code}')

        self.token  = reply.json()['token']
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
            destination wells to transfer to

        volume: float
            volume of fluid to transfer

        '''
        kw = {}
        kw['mount'] = mount
        kw['source'] = source
        kw['dest'] = dest
        kw['volume'] = volume
        print(requests.post(self.url+'/transfer',headers=self.headers,json=kw))
