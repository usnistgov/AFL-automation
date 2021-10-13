from NistoRoboto.APIServer.driver.Driver import Driver
from NistoRoboto.loading.TwoSelectorBlowoutSampleCell import TwoSelectorBlowoutSampleCell
from collections import defaultdict

class OneSelectorBlowoutSampleCell(TwoSelectorBlowoutSampleCell):
    '''
        Class for a sample cell consisting of a pump and a one-to-many flow selector 
        where the pump line holds sample (pulling and pushing as necessary) with a cell on 
        a separate selector channel (in contrast to an inline selector cell where the cell is in the pump line).

        @TODO: write support for multiple cells on separate channels (up to 6 cells on a 10-position selector)


    '''

    def __init__(self,pump,
                      selector,
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
        Driver.__init__(self,name='OneSelectorBlowoutSampleCell',defaults=self.gather_defaults(),overrides=overrides)
        self.pump = pump
        self.selector = selector
        self.blowselector = selector
        self.cell_state = defaultdict(lambda: 'clean')
        self.syringe_dirty = False

        self.rinse_tank_level = rinse_tank_level
        self.waste_tank_level = waste_tank_level
        self.cell_waste_tank_level = cell_waste_tank_level


    def drySyringe(self,blow=True,waittime=1):
        '''
            transfer from air to waste, to push out any residual liquid.
            
            if blow is True, additionally use a 1 s pulse of nitrogen to clear the syringe transfer line.
        '''
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        self.transfer('air','waste',self.config['dry_vol_ml'])
        
        if blow:
            warnings.warn("Cannot blow out transfer line with this driver") 
    
        
    def blowOutCellLegacy(self,cellname='cell'):
        self.pump.setRate(self.config['rinse_speed'])
        self.pump.flow_delay = self.config['rinse_flow_delay']
        self.selector.selectPort('air')
        self.pump.withdraw(self.config['blow_out_vol'],delay=False)
        self.selector.selectPort(cellname)
        self.pump.dispense(self.config['blow_out_vol'])

    def blowOutCell(self,cellname='cell',waittime=20):
        self.blowOutCellLegacy(cellname=cellname)

