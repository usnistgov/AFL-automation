import tiled


from tiled.client.container import DEFAULT_STRUCTURE_CLIENT_DISPATCH, Container

class CatalogOfAFLEvents(Container):
    ''' 
    a subclass of tiled.Container that adds accessor methods to iterate over samples, drivers,
    and convienence methods that let you filter by sample name/driver more easily
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # TODO: set up properties here

    def groupby_sample(self):
        sample_list = self.distinct('sample_uuid')
        
        sample_list = sample_list['metadata']['sample_uuid']
        # this is now list of dicts where each dict is {'value': UUID, 'count': None}

        for sample_uuid in sample_list:
            sample_uuid = sample_uuid['value']
            yield self.search(Eq('sample_uuid',sample_uuid))
        
    def groupby_driver(self):
        driver_list = self.distinct('driver_name')
        
        driver_list = driver_list['metadata']['driver_name']
        # this is now list of dicts where each dict is {'value': UUID, 'count': None}

        for driver_name in driver_list:
            driver_name = driver_name['value']
            yield self.search(Eq('driver_name',driver_name))
        
    def driver(self,driver_name):
        '''shorthand to return only a particular driver
        '''

        return self.search(Eq('driver_name',driver_name))

    def sample_uuid(self,sample_uuid):
        
        return self.search(Eq('sample_uuid',sample_uuid))

    def list_samples(self):

        pass 
