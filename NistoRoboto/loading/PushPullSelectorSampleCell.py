from NistoRoboto.loading.SampleCell import SampleCell

import math

class Tubing():
    tubing = [{'typeid':1530,'material':'Tefzel','IDEXpart':1530,'OD_in':0.125,'ID_mm':1.575},
            {'typeid':1529,'material':'Tefzel','IDEXpart':1529,'OD_in':0.075,'ID_mm':0.254},
            {'typeid':1,'material':'PVC','IDEXpart':0,'OD_in':0.1875,'ID_mm':2.92},
            {'typeid':1517,'material':'Tefzel','IDEXpart':1517,'OD_in':0.075,'ID_mm':1}]

    def __init__(self,specid,length):
        for tubingtype in Tubing.tubing:
            if tubingtype['typeid'] == specid:
                self.id_mm    = tubingtype['ID_mm']
                self.od_in    = tubingtype['OD_in']
                self.idexpart = tubingtype['IDEXpart']
                self.material     = tubingtype['material']
                self.length   = length
                return
        raise NotImplementedError
    
    def volume(self):
        '''returns volume in mL'''
        return (self.id_mm / 20)**2 *math.pi*self.length

class PushPullSelectorSampleCell(SampleCell):
    '''
        Class for a sample cell consisting of a pump and a one-to-many flow selector 
        where the pump line holds sample (pulling and pushing as necessary) with a cell on 
        a separate selector channel (in contrast to an inline selector cell where the cell is in the pump line).

        @TODO: write support for multiple cells on separate channels (up to 6 cells on a 10-position selector)
        @TODO: figure out when/where to pull in air to the syringe to make up for extra_vol_to_empty_ml


    '''



    def __init__(self,pump,selector,ncells=1,name=None,thickness=None,state='clean'):
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
        self.name = name
        self.pump = pump
        self.selector = selector
        self.state = 'clean'
        
        

        self.catch_to_selector_vol = Tubing(1530,2.2*52).volume() + Tubing(1,25.4).volume() + 2.0
        self.cell_to_selector_vol = Tubing(1517,262.9).volume()+1
        self.syringe_to_selector_vol = Tubing(1530,49.27).volume() 
        self.selector_internal_vol = Tubing(1529,1).volume()
        
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
    def loadSample(self,cellname='cell'):

        if self.syringe_dirty:
            self.rinseSyringe()

        if self.state =='dirty':
            self.rinseCell()

            #self.rinseAll()

        if self.state is 'clean':
            self.selector.selectPort('catch')
            self.pump.withdraw(self.catch_to_selector_vol+self.syringe_to_selector_vol+self.catch_empty_ffvol)
            self.selector.selectPort(cellname)
            self.pump.dispense(self.syringe_to_selector_vol + self.cell_to_selector_vol)
            self.state = 'loaded'
        else:
            raise RuntimeError('')

        

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
        self.rinseCellFlood(self,cellname)
        
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
        self.state = 'clean'
        
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
            self.transfer('rinse','catch',self.rinse_vol_ml,vol_dest=self.catch_to_selector_vol)
            for i in range(1):
                self.swish(self.rinse_vol_ml)
            self.transfer('catch','waste',self.catch_to_selector_vol+self.catch_empty_ffvol,self.rinse_vol_ml + self.syringe_to_selector_vol)

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

    def rinseAll(self):
        if self.state is 'loaded':
            self.cellToWaste()
        self.rinseCell()
        self.rinseCatch()
        self.rinseSyringe()



