from NistoRoboto.loading.SampleCell import SampleCell
from NistoRoboto.loading.Tubing import Tubing
from NistoRoboto.DeviceServer.Protocol import Protocol
from collections import defaultdict

import math

class PushPullSelectorSampleCell(Protocol,SampleCell):
    '''
        Class for a sample cell consisting of a pump and a one-to-many flow selector 
        where the pump line holds sample (pulling and pushing as necessary) with a cell on 
        a separate selector channel (in contrast to an inline selector cell where the cell is in the pump line).

        @TODO: write support for multiple cells on separate channels (up to 6 cells on a 10-position selector)
        @TODO: figure out when/where to pull in air to the syringe to make up for extra_vol_to_empty_ml


    '''



    def __init__(self,pump,
                      selector,
                      ncells=1,
                      thickness=None,
                      catch_to_sel_vol=None,
                      cell_to_sel_vol=None,
                      syringe_to_sel_vol=None,
                      selector_internal_vol=None,
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
        self.name = 'PushPullSelectorSampleCell'
        self.pump = pump
        self.selector = selector
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

    def status(self):
        status = []
        status.append(f'State: {dict(self.cell_state)}')
        status.append(f'Pump: {self.pump.name}')
        status.append(f'Selector: {self.selector.name}')
        status.append(f'Cell: {self.name}')
        for k,v in self.selector.portlabels.items():
            status.append(f'Port {v}: {k}')
        return status

    def loadSample(self,cellname='cell'):

        if self.syringe_dirty:
            self.rinseSyringe()

        if not self.cell_state[cellname] =='clean':
            self.rinseCell(cellname=cellname)

        self.selector.selectPort('catch')
        self.pump.withdraw(self.catch_to_selector_vol+self.syringe_to_selector_vol+self.catch_empty_ffvol)
        self.selector.selectPort(cellname)
        self.pump.dispense(self.syringe_to_selector_vol + self.cell_to_selector_vol)
        self.cell_state[cellname] = 'loaded'

        

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

    def catchToWaste(self):
            self.transfer('catch','waste',self.catch_to_selector_vol + self.syringe_to_selector_vol,vol_dest = self.syringe_to_selector_vol + self.to_waste_vol)
            self.syringe_dirty = True

    def cellToWaste(self,cellname='cell'):
            self.transfer(cellname,'waste',self.cell_to_selector_vol + self.syringe_to_selector_vol,vol_dest = self.syringe_to_selector_vol + self.to_waste_vol)
            self.syringe_dirty = True

    def rinseSyringe(self):
        for i in range(self.nrinses_syringe):
            self.transfer('rinse','waste',self.rinse_vol_ml)
        self.syringe_dirty = False

        
    def rinseCell(self,cellname='cell'):
        self.rinseCellFlood(cellname)
        
    def rinseCellPull(self,cellname = 'cell'):
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
        if self.syringe_dirty:
            self.rinseSyringe()
        self.blowOutCell(cellname)
        for i in range(self.nrinses_cell_flood):
            self.transfer('rinse',cellname,self.rinse_vol_ml)
        self.blowOutCell(cellname)
        self.cell_state[cellname] = 'clean'
        
    def transfer(self,source,dest,vol_source,vol_dest=None):
        if vol_dest is None:
            vol_dest = vol_source
        if vol_dest>vol_source:
            self.selector.selectPort('air')
            self.pump.withdraw(vol_dest-vol_source)
        self.selector.selectPort(source)
        self.pump.withdraw(vol_source)
        self.selector.selectPort(dest)
        self.pump.dispense(vol_dest)
        if vol_dest<vol_source:
            self.selector.selectPort('waste')
            self.pump.dispense(vol_source-vol_dest)
        

    def swish(self,vol):
        self.pump.withdraw(vol)
        self.pump.dispense(vol)

    def blowOutCell(self,cellname='cell'):
        self.selector.selectPort('air')
        self.pump.withdraw(self.blow_out_vol)
        self.selector.selectPort(cellname)
        self.pump.dispense(self.blow_out_vol)


    def rinseCatch(self):
        for i in range(self.nrinses_catch):
            from_vol = self.rinse_vol_ml 
            to_vol   = self.rinse_vol_ml + self.catch_to_selector_vol
            self.transfer('rinse','catch',from_vol,to_vol)

            for i in range(1):
                self.swish(self.rinse_vol_ml)

            from_vol = self.rinse_vol_ml + self.catch_to_selector_vol + self.catch_empty_ffvol
            to_vol   = self.rinse_vol_ml + self.syringe_to_selector_vol
            self.transfer('catch','waste',from_vol,to_vol)

    def old_rinseCatch(self):
        for i in range(self.nrinses_catch):
            self.selector.selectPort('air')
            self.pump.withdraw(self.catch_to_selector_vol)
            self.selector.selectPort('rinse')
            self.pump.withdraw(self.rinse_vol_ml)
            self.selector.selectPort('catch')
            self.pump.dispense(self.catch_to_selector_vol)
            for i in range(2): #swish the fluid around in the cell
                self.pump.dispense(self.rinse_vol_ml)
                self.pump.withdraw(self.rinse_vol_ml)
            self.pump.withdraw(self.catch_to_selector_vol)
            self.selector.selectPort('waste')
            self.pump.dispense(self.rinse_vol_ml + self.syringe_to_selector_vol)
            self.selector.selectPort('air')
            self.pump.dispense(self.catch_to_selector_vol-self.syringe_to_selector_vol)

    def rinseAll(self,cellname='cell'):
        # if self.state is 'loaded':
        #     self.cellToWaste()
        self.rinseCell(cellname=cellname)
        self.rinseCatch()
        self.rinseSyringe()



