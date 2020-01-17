from SampleCell import *

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

            selector: a selector object supporting string-based selectPort() method with options 'sample','cell','rinse','waste','air'
                e.g. selector = ViciMultiposSelector(port,portlabels={'sample':1,'cell':2,'rinse':3,'waste':4,'air':5})

        '''
        self.name = name
        self.pump = pump
        self.selector = selector
        self.state = 'clean'

        self.sample_to_hold_volume_ml = 2
        self.sample_to_cell_volume_ml = 3
        self.extra_vol_to_empty_ml = 1
        self.rinse_vol_ml = 3
        self.nrinses_syringe = 2
        self.nrinses_cell = 2

    def loadSample(self,cellname='cell'):

        if self.state is 'dirty':
            self.rinseAll()

        if self.state is 'clean':
            self.selector.selectPort('sample')
            self.pump.withdraw(self.sample_to_hold_volume_ml)
            self.selector.selectPort(cellname)
            self.pump.dispense(self.sample_to_cell_volume_ml)
            self.state = 'loaded'

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

    def sampleToWaste(self):
            self.selector.selectPort('sample')
            self.pump.withdraw(self.sample_to_cell_volume_ml + self.extra_vol_to_empty_ml)
            self.selector.selectPort('waste')
            self.pump.dispense(self.sample_to_waste_volume_ml)

    def cellToWaste(self,cellname='cell'):
            self.selector.selectPort(cellname)
            self.pump.withdraw(self.sample_to_cell_volume_ml + self.extra_vol_to_empty_ml)
            self.selector.selectPort('waste')
            self.pump.dispense(self.sample_to_waste_volume_ml)


    def rinseSyringe(self):
        for i in range(self.nrinses_syringe):
            self.selector.selectPort('rinse')
            self.pump.withdraw(self.rinse_vol_ml)
            self.selector.selectPort('waste')
            self.pump.dispense(self.rinse_vol_ml)

    def rinseCell(self,cellname = 'cell'):
        #rinse the cell
        for i in range(self.nrinses_cell):    
            self.selector.selectPort('rinse')
            self.pump.withdraw(self.rinse_vol_ml)
            self.selector.selectPort(cellname)
            for i in range(3): #swish the fluid around in the cell
                self.pump.dispense(self.rinse_vol_ml)
                self.pump.withdraw(self.rinse_vol_ml)
            self.selector.selectPort('waste')
            self.pump.dispense(self.rinse_vol_ml + self.extra_vol_to_empty_ml)

    def rinseSampleLoadPort(self):
        for i in range(self.nrinses_sampleport):
            self.selector.selectPort('rinse')
            self.pump.withdraw(self.rinse_vol_ml)
            self.selector.selectPort('sample')
            for i in range(3): #swish the fluid around in the cell
                self.pump.dispense(self.rinse_vol_ml+self.sample_to_hold_volume_ml)
                self.pump.withdraw(self.rinse_vol_ml+self.sample_to_hold_volume_ml)
            self.selector.selectPort('waste')
            self.pump.dispense(self.rinse_vol_ml + self.extra_vol_to_empty_ml)

    def rinseAll(self):
        if self.state is 'loaded':
            self.sampleToWaste()
        self.rinseSyringe()
        self.rinseCell()



