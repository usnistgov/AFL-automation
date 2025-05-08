import warnings
from typing import List
from AFL.automation.mixing.MassBalance import MassBalanceDriver
from AFL.automation.APIServer.Driver import Driver
from eic_client.EICClient import EICClient

class BioSANSPrepareDriver(MassBalanceDriver, Driver):
    defaults = {
        'mixing_locations': [],
        'tip_locations': [],
        'prepare_volume': '100 ul',
        'catch_volume': '10 ul',
        'deck': {},
        'stocks': [],
        'stock_mix_order': [],
        'fixed_compositions': {},
        'eic_token': '1',
        'ipts_number': '1234',
        'beamline': 'CG3',
    }

    def __init__(self, overrides=None):
        Driver.__init__(self, name='BioSANSPrepare', defaults=self.gather_defaults(), overrides=overrides)
        self._client = None
        self.stock_pv_map = {}
    
    def status(self):
        """
        Get the status of the BioSANSPrepareDriver.
        """
        status = []
        status.append(f'Stocks: {self.config["targets"]}')
        status.append(f'Stock PV Map: {self.stock_pv_map}')
        status.append(f'{len(self.config["mixing_locations"])} mixing locations left')
        status.append(f'{len(self.config["tip_locations"])} tip locations left')
        return status
            

    def is_feasible(self, targets: List[dict]) -> bool:
        """Check if the target composition is feasible for preparation."""
        # Placeholder: implement feasibility logic
        return True

    def prepare(self, target: dict, dest: str | None):
        """Prepare the target solution at the specified destination."""

        if self.config['fixed_compositions']:
            raise NotImplementedError('Fixed compositions not implemented')

        self.config['targets'] = [target]
        self.balance()

        balanced = self.balanced[0]
        if balanced['balanced_target'] is None:
            raise ValueError(f'No suitable mass balance found for {target["name"]}')
        
        self.make_stock_pv_map()

        for transfer in balanced['balanced_target'].protocol:
            source = self.stock_pv_map[transfer['source']]
            #dest = self.config['mixing_locations'].pop(0)
            self.set_pv(source, transfer['volume'])
        
        # self.config._update_history() # need to do this because we're popping from the list
        

    def transfer(self, src: str, dest: str, volume: str):
        """Transfer a specified volume from src to dest."""
        # Placeholder: implement transfer logic
        pass

    def reset(self):
        """Reset the driver state/configuration."""
        # Placeholder: implement reset logic
        pass 

    @property
    def client(self):
        """
        Property that returns the EIC client instance.
        
        If the client doesn't exist yet, it instantiates a new EICClient
        using the token and beamline from the configuration.
        
        Returns
        -------
        EICClient
            The client instance for communicating with the instrument.
        """
        if self._client is None:
            self._client = EICClient(
                ipts_number=self.config['ipts_number'],
                eic_token=self.config['eic_token'],
                beamline=self.config['beamline']
            )
        return self._client
    
    def make_stock_pv_map(self):
        """
        Make a map of the stock locations to the stock solutions.
        """
        self.stock_pv_map = {}

        num_stocks = 8
        for i in range(num_stocks):
            pv_name = f'CG3:SE:CMP:S{i+1}Vol'
            stock_name = self.get_pv(pv_name + '.DESC')
            self.stock_pv_map[stock_name] = pv_name
    
    def set_pv(self, pv_name, value,timeout=10,wait=True):
        success_set, response_data_set = self.client.set_pv(pv_name, value,timeout,wait)
        if not success_set:
            raise ValueError(f'Failed to set PV {pv_name}')

    def get_pv(self, pv_name, timeout=10):
        success_get, pv_value_read, response_data_get = self.client.get_pv(pv_name, timeout)
        if not success_get:
            raise ValueError(f'Failed to get PV {pv_name}')
        return pv_value_read


_DEFAULT_PORT=5002
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *

    
