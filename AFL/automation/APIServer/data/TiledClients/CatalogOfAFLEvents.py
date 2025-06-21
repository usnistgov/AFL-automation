import tiled

from tqdm.auto import tqdm

from tiled.client.container import DEFAULT_STRUCTURE_CLIENT_DISPATCH, Container
from tiled.queries import Eq

import pandas as pd
import xarray as xr

DIM_NAMES_FOR_DATA = {
        'I': ['q'],
        'dI': ['q'],
        'raw': ['pix_x','pix_y']
        }


class CatalogOfAFLEvents(Container):
    ''' 
    a subclass of tiled.Container that adds accessor methods to iterate over samples, drivers,
    and convienence methods that let you filter by sample name/driver more easily
    '''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # TODO: set up properties here

    def list_samples(self):
        uuids = []
        names = []
        comps = []
        al_campaigns = []

        for sample in tqdm(self.task('set_sample').groupby_sample()):
            try:
                s = sample.items()[-1][1].metadata # just get the last entry, best metadata
                try:
                    uuids.append(s['sample_uuid'])
                except KeyError:
                    uuids.append('')
                try:
                    names.append(s['sample_name'])
                except KeyError:
                    names.append('')
                try:
                    comps.append(s['sample_composition'])
                except KeyError:
                    comps.append('')

                try:
                    al_campaigns.append(s['AL_campaign_name'])
                except KeyError:
                    al_campaigns.append('')
            except Exception as e:
                print(f'Exception {e} while loading sample')
        # make a pd.Dataframe of these results
        df = pd.DataFrame({'uuid':uuids,'name':names,'composition':comps,'al_campaign':al_campaigns})
        return df

    def list_drivers(self):
        return self.distinct('driver_name')['metadata']['driver_name']

    def list_tasks(self):
        return self.distinct('task_name')['metadata']['task_name']


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
        '''
        shorthand to return only a particular driver
        '''
        return self.search(Eq('driver_name',driver_name))

    def sample_uuid(self,sample_uuid):
        return self.search(Eq('sample_uuid',sample_uuid))
    
    def task_uuid(self,task_uuid):
        return self.search(Eq('uuid',task_uuid))

    def task(self,task):
        return self.search(Eq('task_name',task))

    def al_campaign_name(self,al_campaign):
        return self.search(Eq('AL_campaign_name',al_campaign))

    def dataset_for_task(self,task_uuid):
        '''
        return a particular task as an xarray dataset
        '''

        # first, get a subcatalog that contains only this task

        task = self.task_uuid(task_uuid)

        #main_entry = task.search(Eq('array_name',''))

        array_names = task.distinct('array_name')['metadata']['array_name']

        data_vars = {}
        for name in array_names:
            name = name['value']
            array_client = task.search(Eq('array_name',name)).values()
            assert len(array_client)==1, f'Error: more than one array with name {name} found in task {task_uuid}.  Tyler probably wrote this Driver.'
            


            data_vars[name] =  (
                DIM_NAMES_FOR_DATA[name],
                array_client[0].read(),
                array_client[0].metadata
                )

        # for var in data_vars:
        #     if var[0] not in data_vars.keys():
        #         try:
                    
        return xr.Dataset(data_vars, attrs = task.values()[0].metadata)
        #return data_vars

    def __getitem__(self, key):
        # For convenience and backward-compatiblity reasons, we support
        # some "magic" here that is helpful in an interactive setting.
        if isinstance(key, str):
            # CASE 1: Interpret key as a uid or partial uid.
            if len(key) == 36:
                # This looks like a full uid. Try direct lookup first.
                try:
                    return super().__getitem__(key)
                except KeyError:
                    # Fall back to partial uid lookup below.
                    pass
            return self._lookup_by_partial_uid(key)
        elif isinstance(key, numbers.Integral):
            if key > 0:
                # CASE 2: Interpret key as a scan_id.
                return self._lookup_by_scan_id(key)
            else:
                # CASE 3: Interpret key as a recently lookup, as in
                # `catalog[-1]` is the latest entry.
                key = int(key)
                return self.values()[key]
        elif isinstance(key, slice):
            if (key.start is None) or (key.start >= 0):
                raise ValueError(
                    "For backward-compatibility reasons, slicing here "
                    "is limited to negative indexes. "
                    "Use .values() to slice how you please."
                )
            return self.values()[key]
        elif isinstance(key, collections.abc.Iterable):
            # We know that isn't a str because we check that above.
            # Recurse.
            return [self[item] for item in key]
        else:
            raise ValueError(
                "Indexing expects a string, an integer, or a collection of strings and/or integers."
            )
