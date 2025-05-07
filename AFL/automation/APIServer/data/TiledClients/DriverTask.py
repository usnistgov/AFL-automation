import tiled

from tqdm.auto import tqdm

from tiled.client.array import ArrayClient
from tiled.queries import Eq

import datetime

class DriverTask(ArrayClient):
    ''' 
    a subclass of tiled.ArrayClient that adds accessor methods to iterate over samples, drivers,
    and convienence methods that let you filter by sample name/driver more easily
    '''

    def __init__(self, *args, **kwargs):
    	super().__init__(*args, **kwargs)
    	# TODO: set up properties here

    @property
    def start_time(self):
    	return datetime.datetime.strptime(self.metadata['meta']['started'].strip(), '%m/%d/%y %H:%M:%S-%f')

    @property
    def end_time(self):
    	return datetime.datetime.strptime(self.metadata['meta']['ended'].strip(), '%m/%d/%y %H:%M:%S-%f')
    
    @property
    def queued_time(self):
    	return datetime.datetime.strptime(self.metadata['meta']['queued'].strip(), '%m/%d/%y %H:%M:%S-%f')
    
    @property
    def exit_state(self):
    	return self.metadata['meta']['exit_state']
    
    @property
    def return_val(self):
    	return self.metadata['meta']['return_val']
    
    
    @property
    def task_name(self):
    	return self.metadata['task_name']

    @property
    def task(self):
    	return self.metadata['task']
    

    