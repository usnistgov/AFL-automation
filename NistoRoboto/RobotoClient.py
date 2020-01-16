import NistoRoboto.RobotoFlaskKey
import requests

class RobotoClient:
    def __init__(self,url = 'http://10.42.0.31:5000/'):
        self.url = url
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
        kw['key'] = NistoRoboto.RobotoFlaskKey.__flaskkey__
        kw['mount'] = mount
        kw['source'] = source
        kw['dest'] = dest
        kw['volume'] = volume
        print(requests.post(self.url+'/transfer',json=kw))
