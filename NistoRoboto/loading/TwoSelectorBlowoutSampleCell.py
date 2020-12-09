from NistoRoboto.loading.SampleCell import SampleCell
from NistoRoboto.loading.Tubing import Tubing
from NistoRoboto.APIServer.driver.Driver import Driver
from collections import defaultdict
import time

import math

class TwoSelectorBlowoutSampleCell(Driver,SampleCell):
    '''
        Class for a sample cell consisting of a pump and a one-to-many flow selector 
        where the pump line holds sample (pulling and pushing as necessary) with a cell on 
        a separate selector channel (in contrast to an inline selector cell where the cell is in the pump line).

        @TODO: write support for multiple cells on separate channels (up to 6 cells on a 10-position selector)
        @TODO: figure out when/where to pull in air to the syringe to make up for extra_vol_to_empty_ml


    '''



    def __init__(self,pump,
                      selector,
                      blowselector,
                      ncells=1,
                      thickness=None,
                      catch_to_sel_vol=None,
                      cell_to_sel_vol=None,
                      syringe_to_sel_vol=None,
                      selector_internal_vol=None,
                      calibrated_catch_to_syringe_vol=None,
                      calibrated_syringe_to_cell_vol=None,
                      rinse_speed=1.0,
                      load_speed=0.5,
                      rinse_flow_delay=3.0,
                      load_flow_delay=10.0,
                      ):
        '''
            ncells = number of connected cells (up to 6 cells with a 10-position flow selector, with four positions taken by load port, rinse, waste, and air)
            Name = the cell name, array with length = ncells

            thickness = cell path length, to be incorporated into metadata, array with length = ncells

            cell state if not 'clean', array with length = ncells

            pump: a pump object supporting withdraw() and dispense() methods
                e.g. pump = NE1KSyringePump(port,syringe_id_mm,syringe_volume)

            selector: a selector object supporting string-based selectPort() method with options 'catch','cell','rinse','waste','air'
                e.g. selector = ViciMultiposSelector(port,portlabels={'catch':1,'cell':2,'rinse':3,'waste':4,'air':5})

        '''
        self._app = None
        self.name = 'TwoSelectorBlowoutSampleCell'
        self.pump = pump
        self.selector = selector
        self.blowselector = blowselector
        self.cell_state = defaultdict(lambda: 'clean')
        
        

        if catch_to_sel_vol is None:
            self.catch_to_selector_vol   = Tubing(1530,2.2*52).volume() + Tubing(1,25.4).volume() + 2.0
        else:
            self.catch_to_selector_vol   = catch_to_sel_vol

        if cell_to_sel_vol is None:
            self.cell_to_selector_vol    = Tubing(1517,262.9).volume()  + 1
        else:
            self.cell_to_selector_vol    = cell_to_sel_vol

        if syringe_to_sel_vol is None:
            self.syringe_to_selector_vol = Tubing(1530,49.27).volume() 
        else:
            self.syringe_to_selector_vol = syringe_to_sel_vol

        if selector_internal_vol is None:
            self.selector_internal_vol   = Tubing(1529,1).volume()
        else:
            self.selector_internal_vol   = selector_internal_vol
        
        self.calibrated_catch_to_syringe_vol  = calibrated_catch_to_syringe_vol
        self.calibrated_syringe_to_cell_vol  = calibrated_syringe_to_cell_vol 

        self.catch_empty_ffvol = 2
        self.to_waste_vol = 1

        self.rinse_prime_vol = 3

        self.rinse_vol_ml = 3
        self.blow_out_vol = 6
        self.nrinses_cell_flood = 2
        self.nrinses_syringe = 2
        self.nrinses_cell = 1
        self.nrinses_catch = 2
        self.syringe_dirty = False
        
        self.rinse_speed = rinse_speed
        self.load_speed = load_speed
        self.rinse_flow_delay = rinse_flow_delay
        self.load_flow_delay = load_flow_delay
        self.pump.setRate(self.rinse_speed)

        #variables that we'll allow users to set via the API
        self.remote_parameters = [
            'calibrated_catch_to_syringe_vol',
            'calibrated_syringe_to_cell_vol',
            'catch_to_selector_vol',
            'cell_to_selector_vol',
            'syringe_to_selector_vol',
            'selector_internal_vol',
            'catch_empty_ffvol',
            'to_waste_vol',
            'rinse_prime_vol',
            'rinse_vol_ml',
            'blow_out_vol',
            'nrinses_cell_flood',
            'nrinses_syringe',
            'nrinses_cell',
            'nrinses_catch',
            'syringe_dirty',
            'rinse_speed',
            'load_speed',
            'rinse_flow_delay',
            'load_flow_delay',
            ]

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self,app):
        self._app = app
        self.pump.app = app
        self.selector.app = app

    def status(self):
        status = []
        status.append(f'CellState: {dict(self.cell_state)}')
        status.append(f'SelectorState: {self.selector.portString}')
        status.append(f'BlowSelectorState: {self.blowselector.portString}')
        status.append(f'Pump: {self.pump.name}')
        status.append(f'Selector: {self.selector.name}')
        status.append(f'BlowSelector: {self.blowselector.name}')
        status.append(f'Cell: {self.name}')
        for k,v in self.selector.portlabels.items():
            status.append(f'Port {v}: {k}')
        return status
    
    def setParameter(self,parameter,value):
        if parameter not in self.remote_parameters:
            raise ValueError(f'Parameter {parameter} not settable')
        else:
            setattr(self,parameter,value)

    def getParameters(self):
        for parameter in self.remote_parameters:
            value = getattr(self,parameter)
            print(f'{parameter:30s} = {value}')

    def transfer(self,source,dest,vol_source,vol_dest=None):
        if vol_dest is None:
            vol_dest = vol_source
        self.app.logger.debug(f'Transferring {vol_source}mL from {source} and {vol_dest}mL to {dest}')

        if vol_dest>vol_source:
            self.app.logger.debug(f'Withrawing {vol_dest-vol_source} mL from air')
            self.selector.selectPort('air')
            self.pump.withdraw(vol_dest-vol_source,delay=False)

        self.selector.selectPort(source)
        self.pump.withdraw(vol_source)
        self.selector.selectPort(dest)
        self.pump.dispense(vol_dest)
        if vol_dest<vol_source:
            self.app.logger.debug(f'Dumping {vol_source-vol_dest} mL  excess to waste')
            self.selector.selectPort('waste')
            self.pump.dispense(vol_source-vol_dest)

    def catchToSyringe(self,sampleVolume=0):
        self.pump.setRate(self.load_speed)
        self.pump.flow_delay = self.load_flow_delay

        vol_source = self.catch_to_selector_vol+self.syringe_to_selector_vol+self.catch_empty_ffvol + sampleVolume

        self.selector.selectPort('catch')
        self.pump.withdraw(vol_source)

    def loadSample(self,cellname='cell',sampleVolume=0):

        if self.syringe_dirty:
            self.rinseSyringe()

        if not self.cell_state[cellname] =='clean':
            self.rinseCell(cellname=cellname)
        
        self.pump.setRate(self.load_speed)
        self.pump.flow_delay = self.load_flow_delay

        if (self.calibrated_catch_to_syringe_vol is None) or (self.calibrated_catch_to_syringe_vol=='None'):
            vol_source  = self.catch_to_selector_vol
            vol_source += self.syringe_to_selector_vol
            vol_source +=self.catch_empty_ffvol 
        else:
            vol_source = self.calibrated_catch_to_syringe_vol

        if (self.calibrated_syringe_to_cell_vol is None) or (self.calibrated_syringe_to_cell_vol=='None'):
            vol_dest  = self.syringe_to_selector_vol 
            vol_dest += self.cell_to_selector_vol 
        else:
            vol_dest = self.calibrated_syringe_to_cell_vol
            
        vol_dest   += sampleVolume
        vol_source += sampleVolume
        self.transfer('catch',cellname,vol_source,vol_dest)

        # self.selector.selectPort('catch')
        # self.pump.withdraw(self.catch_to_selector_vol+self.syringe_to_selector_vol+self.catch_empty_ffvol)
        # self.selector.selectPort(cellname)
        # self.pump.dispense(self.syringe_to_selector_vol + self.cell_to_selector_vol)
        self.cell_state[cellname] = 'loaded'
        
        self.pump.setRate(self.rinse_speed)
        self.pump.flow_delay = self.rinse_flow_delay

    def _firstCleanCell(self,rinse_if_none=False):
            # find the first clean cell and use that.
            for (cn,ct,cs) in zip(self.name,self.thickness,self.state):
                if cs is 'clean':
                    return (cn,ct,cs)
            if clean_if_none:
                for (cn,ct,cs) in zip(self.name,self.thickness,self.state):
                    if cs is 'dirty':
                        self.rinseCell(cellname=cn)
                        return (cn,ct,cs)

    def catchToWaste(self,sampleVolume=0.0):
        if (self.calibrated_catch_to_syringe_vol is None) or (self.calibrated_catch_to_syringe_vol=='None'):
            vol_source = self.syringe_to_selector_vol
            vol_source +=self.catch_empty_ffvol 
            vol_source += sampleVolume
        else:
            vol_source = self.calibrated_catch_to_syringe_vol 
            vol_source += sampleVolume
        

        vol_dest = self.syringe_to_selector_vol + self.to_waste_vol + sampleVolume
        self.transfer('catch','waste',vol_source,vol_dest)
        self.syringe_dirty = True

    def cellToWaste(self,cellname='cell'):
            self.transfer(cellname,'waste',self.cell_to_selector_vol + self.syringe_to_selector_vol,vol_dest = self.syringe_to_selector_vol + self.to_waste_vol)
            self.syringe_dirty = True

    def rinseSyringe(self):
        self.pump.setRate(self.rinse_speed)
        self.pump.flow_delay = self.rinse_flow_delay
        for i in range(self.nrinses_syringe):
            self.transfer('rinse','waste',self.rinse_vol_ml)
        self.syringe_dirty = False

        
    def rinseCell(self,cellname='cell'):
        self.pump.setRate(self.rinse_speed)
        self.pump.flow_delay = self.rinse_flow_delay
        self.rinseCellFlood(cellname)
        
    def rinseCellPull(self,cellname = 'cell'):
        self.pump.setRate(self.rinse_speed)
        self.pump.flow_delay = self.rinse_flow_delay
        #rinse the cell
        for i in range(self.nrinses_cell):    
            self.selector.selectPort('rinse')
            self.pump.withdraw(self.rinse_vol_ml)
            self.selector.selectPort(cellname)
            for i in range(3): #swish the fluid around in the cell
                self.pump.dispense(self.rinse_vol_ml)
                self.pump.withdraw(self.rinse_vol_ml)
            self.selector.selectPort('waste')
            self.pump.dispense(self.rinse_vol_ml + self.to_waste_vol)
        self.syringe_dirty = True

    def rinseCellFlood(self,cellname='cell'):
        self.pump.setRate(self.rinse_speed)
        self.pump.flow_delay = self.rinse_flow_delay
        if self.syringe_dirty:
            self.rinseSyringe()
        self.blowOutCell(cellname)
        for i in range(self.nrinses_cell_flood):
            self.transfer('rinse',cellname,self.rinse_vol_ml)
        self.blowOutCell(cellname)
        self.cell_state[cellname] = 'clean'
        

    def swish(self,vol):
        self.pump.setRate(self.rinse_speed)
        self.pump.flow_delay = self.rinse_flow_delay
        self.pump.withdraw(vol)
        self.pump.dispense(vol)

    def blowOutCellLegacy(self,cellname='cell'):
        self.pump.setRate(self.rinse_speed)
        self.pump.flow_delay = self.rinse_flow_delay
        self.selector.selectPort('air')
        self.pump.withdraw(self.blow_out_vol,delay=False)
        self.selector.selectPort(cellname)
        self.pump.dispense(self.blow_out_vol)

    def blowOutCell(self,cellname='cell',waittime=20):
        self.selector.selectPort('cell')
        self.blowselector.selectPort('blow')
        time.sleep(waittime)
        self.blowselector.selectPort('pump')

    def rinseCatch(self):
        self.pump.setRate(self.rinse_speed)
        self.pump.flow_delay = self.rinse_flow_delay


        for i in range(self.nrinses_catch):
            from_vol = self.rinse_vol_ml + self.syringe_to_selector_vol
            if (self.calibrated_catch_to_syringe_vol is None) or (self.calibrated_catch_to_syringe_vol=='None'):
                to_vol   = self.rinse_vol_ml + self.catch_to_selector_vol
            else:
                to_vol   = self.calibrated_catch_to_syringe_vol + self.rinse_vol_ml
            self.transfer('rinse','catch',from_vol,to_vol)

            for i in range(1):
                self.swish(self.rinse_vol_ml)

            if (self.calibrated_catch_to_syringe_vol is None) or (self.calibrated_catch_to_syringe_vol=='None'):
                from_vol = self.rinse_vol_ml + self.catch_to_selector_vol + self.catch_empty_ffvol
            else:
                from_vol   = self.calibrated_catch_to_syringe_vol + self.catch_empty_ffvol + self.rinse_vol_ml
            to_vol   = self.rinse_vol_ml + self.syringe_to_selector_vol
            self.transfer('catch','waste',from_vol,to_vol)

        #clear out any remaining volume in the syringe
        self.selector.selectPort('waste')
        self.pump.emptyStringe()

    def rinseAll(self,cellname='cell'):
        # if self.state is 'loaded':
        #     self.cellToWaste()
        self.rinseCell(cellname=cellname)
        self.rinseCatch()
        self.rinseSyringe()



