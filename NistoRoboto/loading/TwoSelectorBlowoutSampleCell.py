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


    '''
    defaults={}
    defaults['ncells'] = 1
    defaults['thickness'] = None
    defaults['catch_to_selector_vol'] = Tubing(1517,112).volume()
    defaults['cell_to_selector_vol'] = Tubing(1517,170).volume()+0.6
    defaults['syringe_to_selector_vol'] = Tubing(1530,49.27+10.4).volume() 
    defaults['selector_internal_vol'] = Tubing(1529,1).volume()
    defaults['calibrated_catch_to_syringe_vol'] = 1.1
    defaults['calibrated_syringe_to_cell_vol'] = 3.2
    defaults['rinse_speed'] = 50.0
    defaults['load_speed'] = 10.0
    defaults['rinse_flow_delay'] = 3.0
    defaults['load_flow_delay'] = 10.0
    defaults['catch_empty_ffvol'] = 2
    defaults['to_waste_vol'] = 1
    defaults['rinse_prime_vol'] = 3
    defaults['rinse_vol_ml'] = 3
    defaults['dry_vol_ml'] = 5
    defaults['blow_out_vol'] = 6
    defaults['nrinses_cell_flood'] = 2
    defaults['nrinses_syringe'] = 2
    defaults['nrinses_cell'] = 1
    defaults['nrinses_catch'] = 2

    def __init__(self,pump,
                      selector,
                      blowselector,
                      rinse_tank_level=950,
                      waste_tank_level=0,
                      cell_waste_tank_level=0,
                      overrides=None, 
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
        Driver.__init__(self,name='TwoSelectorBlowoutSampleCell',defaults=self.gather_defaults(),overrides=overrides)
        self.pump = pump
        self.selector = selector
        self.blowselector = blowselector
        self.cell_state = defaultdict(lambda: 'clean')
        self.syringe_dirty = False

        self.rinse_tank_level = rinse_tank_level
        self.waste_tank_level = waste_tank_level
        self.cell_waste_tank_level = cell_waste_tank_level

    def reset_tank_levels(self,rinse=950,waste=0,cell_waste=0):
        self.rinse_tank_level = rinse
        self.waste_tank_level = waste
        self.cell_waste_tank_level = cell_waste

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self,app):
        if app is None:
            self._app = app
        else:
            self._app = app
            self.pump.app = app
            self.selector.app = app

    def status(self):
        status = []
        status.append(f'CellState: {dict(self.cell_state)}')
        status.append(f'SelectorState: {self.selector.portString}')
        status.append(f'BlowSelectorState: {self.blowselector.portString}')
        status.append(f'Rinse tank: {self.rinse_tank_level} mL')
        status.append(f'Waste tank: {self.waste_tank_level} mL')
        status.append(f'Cell Waste: {self.cell_waste_tank_level} mL')
        status.append(f'Pump: {self.pump.name}')
        status.append(f'Selector: {self.selector.name}')
        status.append(f'BlowSelector: {self.blowselector.name}')
        status.append(f'Cell: {self.name}')
        for k,v in self.selector.portlabels.items():
            status.append(f'Port {v}: {k}')
        return status
    
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

        if source == 'rinse':
            self.rinse_tank_level -= vol_source

        if dest == 'waste':
            self.waste_tank_level += vol_dest

        if dest == 'cell':
            self.cell_waste_tank_level += min(vol_source,vol_dest)


    def catchToSyringe(self,sampleVolume=0):
        self.pump.setRate(self.config['load_speed'])
        self.pump.flow_delay = self.config['load_flow_delay']

        vol_source = self.config['catch_to_selector_vol']+self.config['syringe_to_selector_vol']+self.config['catch_empty_ffvol'] + sampleVolume

        self.selector.selectPort('catch')
        self.pump.withdraw(vol_source)

    def loadSample(self,cellname='cell',sampleVolume=0):

        if self.syringe_dirty:
            self.rinseSyringe()

        if not self.cell_state[cellname] =='clean':
            self.rinseCell(cellname=cellname)
       
        self.drySyringe()

        self.pump.setRate(self.config['load_speed'])
        self.pump.flow_delay = self.config['load_flow_delay']

        if (self.config['calibrated_catch_to_syringe_vol'] is None) or (self.config['calibrated_catch_to_syringe_vol']=='None'):
            vol_source  = self.config['catch_to_selector_vol']
            vol_source += self.config['syringe_to_selector_vol']
            vol_source +=self.config['catch_empty_ffvol'] 
        else:
            vol_source = self.config['calibrated_catch_to_syringe_vol']

        if (self.config['calibrated_syringe_to_cell_vol'] is None) or (self.config['calibrated_syringe_to_cell_vol']=='None'):
            vol_dest  = self.config['syringe_to_selector_vol'] 
            vol_dest += self.config['cell_to_selector_vol'] 
        else:
            vol_dest = self.config['calibrated_syringe_to_cell_vol']
            
        vol_dest   += sampleVolume
        vol_source += sampleVolume
        self.transfer('catch',cellname,vol_source,vol_dest)

        # self.selector.selectPort('catch')
        # self.pump.withdraw(self.config['catch_to_selector_vol']+self.config['syringe_to_selector_vol']+self.config['catch_empty_ffvol'])
        # self.selector.selectPort(cellname)
        # self.pump.dispense(self.config['syringe_to_selector_vol'] + self.config['cell_to_selector_vol'])
        self.cell_state[cellname] = 'loaded'
        
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']

    def _firstCleanCell(self,rinse_if_none=False):
            # find the first clean cell and use that.
            for (cn,ct,cs) in zip(self.name,self.config['thickness'],self.state):
                if cs is 'clean':
                    return (cn,ct,cs)
            if clean_if_none:
                for (cn,ct,cs) in zip(self.name,self.config['thickness'],self.state):
                    if cs is 'dirty':
                        self.rinseCell(cellname=cn)
                        return (cn,ct,cs)

    def catchToWaste(self,sampleVolume=0.0):
        if (self.config['calibrated_catch_to_syringe_vol'] is None) or (self.config['calibrated_catch_to_syringe_vol']=='None'):
            vol_source = self.config['syringe_to_selector_vol']
            vol_source +=self.config['catch_empty_ffvol'] 
            vol_source += sampleVolume
        else:
            vol_source = self.config['calibrated_catch_to_syringe_vol'] 
            vol_source += sampleVolume
        

        vol_dest = self.config['syringe_to_selector_vol'] + self.config['to_waste_vol'] + sampleVolume
        self.transfer('catch','waste',vol_source,vol_dest)
        self.syringe_dirty = True

    def cellToWaste(self,cellname='cell'):
            self.transfer(cellname,'waste',self.config['cell_to_selector_vol'] + self.config['syringe_to_selector_vol'],vol_dest = self.config['syringe_to_selector_vol'] + self.config['to_waste_vol'])
            self.syringe_dirty = True

    def rinseSyringe(self):
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        for i in range(self.config['nrinses_syringe']):
            self.transfer('rinse','waste',self.config['rinse_vol_ml'])
        self.syringe_dirty = False

    def drySyringe(self,blow=True,waittime=1):
        '''
            transfer from air to waste, to push out any residual liquid.
            
            if blow is True, additionally use a 1 s pulse of nitrogen to clear the syringe transfer line.
        '''
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        self.transfer('air','waste',self.config['dry_vol_ml'])
        
        if blow:
            self.selector.selectPort('waste')
            self.blowselector.selectPort('blow')
            time.sleep(waittime)
            self.blowselector.selectPort('pump')
        
    def rinseCell(self,cellname='cell'):
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        self.rinseCellFlood(cellname)
        
    def rinseCellPull(self,cellname = 'cell'):
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        #rinse the cell
        for i in range(self.config['nrinses_cell']):    
            self.selector.selectPort('rinse')
            self.pump.withdraw(self.config['rinse_vol_ml'])
            self.selector.selectPort(cellname)
            for i in range(3): #swish the fluid around in the cell
                self.pump.dispense(self.config['rinse_vol_ml'])
                self.pump.withdraw(self.config['rinse_vol_ml'])
            self.selector.selectPort('waste')
            self.pump.dispense(self.config['rinse_vol_ml'] + self.config['to_waste_vol'])
        self.syringe_dirty = True

    def rinseCellFlood(self,cellname='cell'):
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        if self.syringe_dirty:
            self.rinseSyringe()
        self.blowOutCell(cellname)
        for i in range(self.config['nrinses_cell_flood']):
            self.transfer('rinse',cellname,self.config['rinse_vol_ml'])
        self.blowOutCell(cellname)
        self.cell_state[cellname] = 'clean'
        

    def swish(self,vol):
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        self.pump.withdraw(vol)
        self.pump.dispense(vol)

    def blowOutCellLegacy(self,cellname='cell'):
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        self.selector.selectPort('air')
        self.pump.withdraw(self.config['blow_out_vol'],delay=False)
        self.selector.selectPort(cellname)
        self.pump.dispense(self.config['blow_out_vol'])

    def blowOutCell(self,cellname='cell',waittime=20):
        self.selector.selectPort('cell')
        self.blowselector.selectPort('blow')
        time.sleep(waittime)
        self.blowselector.selectPort('pump')

    def rinseCatch(self):
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']


        for i in range(self.config['nrinses_catch']):
            from_vol = self.config['rinse_vol_ml'] + self.config['syringe_to_selector_vol']
            if (self.config['calibrated_catch_to_syringe_vol'] is None) or (self.config['calibrated_catch_to_syringe_vol']=='None'):
                to_vol   = self.config['rinse_vol_ml'] + self.config['catch_to_selector_vol']
            else:
                to_vol   = self.config['calibrated_catch_to_syringe_vol'] + self.config['rinse_vol_ml']
            self.transfer('rinse','catch',from_vol,to_vol)

            for i in range(1):
                self.selector.selectPort('catch')
                self.swish(self.config['rinse_vol_ml'])

            if (self.config['calibrated_catch_to_syringe_vol'] is None) or (self.config['calibrated_catch_to_syringe_vol']=='None'):
                from_vol = self.config['rinse_vol_ml'] + self.config['catch_to_selector_vol'] + self.config['catch_empty_ffvol']
            else:
                from_vol   = self.config['calibrated_catch_to_syringe_vol'] + self.config['catch_empty_ffvol'] + self.config['rinse_vol_ml']
            to_vol   = self.config['rinse_vol_ml'] + self.config['syringe_to_selector_vol']
            self.transfer('catch','waste',from_vol,to_vol)

        #clear out any remaining volume in the syringe
        self.selector.selectPort('waste')
        self.pump.emptySyringe()

    def rinseAll(self,cellname='cell'):
        # if self.state is 'loaded':
        #     self.cellToWaste()
        self.rinseCell(cellname=cellname)
        self.rinseCatch()
        self.rinseSyringe()

    def setRinseLevel(self,vol):
        self.rinse_tank_level = vol

    def setWasteLevel(self,vol):
        self.waste_tank_level = vol


