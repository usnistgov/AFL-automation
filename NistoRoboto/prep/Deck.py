import numpy as np
from NistoRoboto.prep.Sample import Sample
from NistoRoboto.prep.SampleSeries import SampleSeries
from NistoRoboto.prep.Mixture import Mixture
from NistoRoboto.prep.MassBalance import MassBalance
from NistoRoboto.prep.PipetteAction import PipetteAction
from NistoRoboto.shared.exceptions import MixingException
from NistoRoboto.shared.units import units
import scipy.optimize

get_pipette='''
def get_pipette(volume,loaded_pipettes):
    found_pipettes = []
    minVol = ''
    for pipette in loaded_pipettes:
        minVol += f'{pipette.min_volume}>{volume}\\n'
        if volume>pipette.min_volume:
            found_pipettes.append(pipette)

    if not found_pipettes:
        raise ValueError('No suitable pipettes found!\\n'+ minVol)
    else:
        return min(found_pipettes,key=lambda x: x.max_volume)
'''

metadata = '''
metadata = {
    'protocolName': 'Alignment',
    'author': 'NistoRoboto',
    'description': 'Script for aligning and testing',
    'apiLevel': '2.0'
}
'''


class Deck:
    def __init__(self):
        self.reset_targets()
        self.reset_stocks()

        self.mass_cutoff = 1.0*units('ug')
        self.volume_cutoff = 30*units('ul')
        
        self.protocol = []
        self.protocol_checks = []
        self.sample_series = SampleSeries()

        self.tip_racks    = {}
        self.containers    = {}
        self.pipettes      = {}
        self.catches = {}

        self.balancer = MassBalance()

        self.client = None

    def init_remote_connection(self,url,home=False):
        from NistoRoboto.APIServer.client.OT2Client import OT2Client
        self.client = OT2Client(url)
        self.client.login('NistoRobotoDeck')
        if home:
            self.client.debug(state=False)
            self.client.home()# must home robot before sending commands

    def catch_sample(self,volume,source,dest,mix_before=None,debug_mode=False):
        if self.client is None:
            raise ValueError('Need to call \'init_remote_connection\' before sending protocol')

        if not self.client.logged_in():
            # just re-login
            self.client.login('NistoRobotoDeck')

        self.client.debug(state=False)#unlock the queue

        kw = {}
        kw['volume'] = volume
        kw['source'] = source
        kw['dest']   = dest
        kw['mix_before']   = mix_before
        UUID = self.client.transfer(**kw)
        return UUID

    def _check_client(self,debug_mode=False):

        if self.client is None:
            raise ValueError('Need to call \'init_remote_connection\' before sending protocol')

        if not self.client.logged_in():
            # just re-login
            self.client.login('NistoRobotoDeck')

        self.client.debug(state=False)#unlock the queue

    def send_deck_config(self,debug_mode=False):
        self._check_client(debug_mode)

        # tip racks must be in place *before* adding pipettes
        for slot,tip_rack in self.tip_racks.items():
            self.client.load_labware(tip_rack,slot)

        for slot,container in self.containers.items():
            self.client.load_labware(container,slot)

        for slot,catch in self.catches.items():
            self.client.load_labware(catch,slot)

        for mount,(pipette,tip_rack_slots) in self.pipettes.items():
            self.client.load_instrument(pipette,mount,tip_rack_slots)

    def send_protocol(self,send_deck_config=True,debug_mode=False):
        if not self.protocol:
            raise ValueError('No protocol to send. Did you call make_protocol()?')

        self._check_client(debug_mode)

        if send_deck_config:
            self.send_deck_config(debug_mode)

        for task in self.protocol:
            kw = task.get_kwargs()
            UUID = self.client.transfer(**kw)
        return UUID

    def add_pipette(self,name,mount,tipracks):
        if not (mount in ['left','right']):
            raise ValueError('Pipette mount point can only be "left" or "right"')

        tiprack_list = []
        for slot,rack_name in tipracks:
            self.tip_racks[slot] = rack_name
            tiprack_list.append(slot)

        self.pipettes[mount] = name,tiprack_list

    def add_catch(self,name,slot):
        self.catches[slot] = name

    def add_container(self,name,slot):
        self.containers[slot] = name

    def add_stock(self,stock,location):
        stock = stock.copy()
        self.stocks.append(stock)
        self.stock_location[stock] = location
            
    def add_target(self,target,location):
        target = target.copy()
        self.targets.append(target)
        self.target_location[target] = location
        
    def reset_targets(self):
        self.targets = []
        self.target_location = {}
            
    def reset_stocks(self):
        self.stocks = []
        self.stock_location = {}

    def get_components(self):
        components        = set()
        target_components = set()
        stock_components  = set()

        for target in self.targets:
            for name,component in target:
                components.add(name)
                target_components.add(name)

        for stock in self.stocks:
            for name,component in stock:
                components.add(name)
                stock_components.add(name)

        return components,target_components,stock_components


    def make_sample_series(self,reset_sample_series=False):
        #build component list
        self.balancer.reset_stocks()
        for stock in self.stocks:
            self.balancer.add_stock(stock,self.stock_location[stock])

        if reset_sample_series:
            self.sample_series.reset()

        for target in self.targets:
            self.balancer.reset_targets()
            self.balancer.set_target(target,self.target_location[target])
            self.balancer.balance_mass()
            
            if any([i[1]<0 for i in self.balancer.mass_transfers.values()]):
                raise MixingException(f'Mass transfer calculation failed, negative mass transers present:\n{self.balancer.mass_transfers}')

            target_check = Mixture()
            for stock,(stock_loc,mass) in self.balancer.mass_transfers.items():
                if mass>self.mass_cutoff:#tolerance
                    removed = stock.copy()
                    removed.mass = mass

                    ##if this is changed, make_protocol needs to be updated
                    if (removed.volume>0) and (removed.volume<self.volume_cutoff):
                        continue

                    target_check = target_check + removed


            #need to add empty components for equality check
            for name,component in target:
                if not target_check.contains(name):
                    c = component.copy()
                    c._mass = 0.0*units('g')
                    target_check = target_check + c

            sample = Sample( 
                    target=target,
                    target_check = target_check,
                    balancer = self.balancer,
                    )
            self.sample_series.add_sample(sample)
        return self.sample_series

                    
    def validate_sample_series(self,tolerance=0.0,print_report=True):
        validated = []
        self.validation_report = []
        for sample,_ in self.sample_series:
            report = f'==> Attempting to make {sample.target.volume.to("ml")}  of {sample.target.mass_fraction}\n'
            for stock,(stock_loc,mass) in sample.balancer.mass_transfers.items():
                if (mass>0) and (mass<self.mass_cutoff):
                    report += f'\t--> Skipping {mass} of {stock} (mass cutoff={self.mass_cutoff})\n'

                removed = stock.copy()
                removed.mass=mass
                if (removed.volume>0) and (removed.volume<self.volume_cutoff):
                    report+= f'\t--> Skipping {removed.volume} of {removed}. (volume cutoff={self.volume_cutoff})\n'

            if not (sample.target == sample.target_check):
                report += f'\t~~> Target mass/vol:  {sample.target.mass}/{sample.target.volume}\n'
                report += f'\t~~> Result mass/vol:  {sample.target.mass}/{sample.target.volume}\n'
                report += f'\t~~> Target mass_frac: {sample.target.mass_fraction}\n'
                report += f'\t~~> Result mass_frac: {sample.target_check.mass_fraction}\n'
                diffs = []
                for name in sample.target.components.keys():
                    phi_tc = sample.target_check.mass_fraction[name]
                    phi_t = sample.target.mass_fraction[name]
                    diff = (phi_tc - phi_t)/(phi_tc)
                    diffs.append(diff/100)
                    report += f'\t\t~~> {name} frac difference: {diff}\n'

                diffs = np.array(diffs)
                diffs = diffs[~np.isnan(diffs)]
                diffs = np.abs(diffs)
                if all(diffs<=tolerance):
                    report += f'--> Target Tolerable!\n'
                    validated.append(True)
                else:
                    report += f'~~> Target Failed...\n'
                    validated.append(False)
            else:
                report += f'==> Target Successful!\n'
                validated.append(True)
            report += '-------------------------------------------\n'
            self.validation_report.append(report)
        self.sample_series.validated = validated
        if print_report:
            for report in self.validation_report:
                print(report)
        return self.sample_series

    def make_protocol(self,only_validated=False,flatten=False):
        self.protocol = []
        for sample,validated in self.sample_series:
            if only_validated and (not validated):
                print('Skipping not-validated or invalidated sample')
                continue

            sample_protocol = []
            for stock,(stock_loc,mass) in sample.balancer.mass_transfers.items():
                if mass>self.mass_cutoff:#tolerance
                    removed = stock.copy()
                    removed.mass = mass

                    ##if this is changed, balance_mass needs to be updated
                    if (removed.volume>0) and (removed.volume<self.volume_cutoff):
                        continue
                    
                    action = PipetteAction(
                                source = stock_loc,
                                dest = sample.balancer.target_location,
                                volume = removed.volume.to('ul').magnitude, #convet from ml for to ul
                                dest_loc = 'top'
                                
                    )
                    sample_protocol.append(action)
            self.protocol.append(sample_protocol)

        if flatten:
            return [action for action_group in self.protocol for action in action_group]
        else:
            return self.protocol
        
    def make_align_script(self,filename,load_last_sample=True):
        with open(filename,'w') as f:
            f.write('from opentrons import protocol_api\n')
            f.write('\n')
            f.write('\n')
            f.write(metadata)
            f.write('\n')
            f.write('\n')
            f.write(get_pipette)
            f.write('\n')
            f.write('\n')
            f.write('def run(protocol):\n')

            
            f.write('\n')
            for slot,tiprack in self.tip_racks.items():
                f.write(' '*4+ f'tiprack_{slot} = protocol.load_labware(\'{tiprack}\',\'{slot}\')\n')
            f.write('\n')

            for slot,container in self.containers.items():
                f.write(' '*4 + f'container_{slot} = protocol.load_labware(\'{container}\',\'{slot}\')\n')
            f.write('\n')

            for slot,catch in self.catches.items():
                f.write(' '*4 + f'catch_{slot} = protocol.load_labware(\'{catch}\',\'{slot}\')\n')
            f.write('\n')

            f.write(' '*4 + 'pipettes = []\n')
            for mount,(pipette,tip_rack_slots) in self.pipettes.items():
                
                f.write(' '*4 + f'tip_racks = []\n')
                f.write(' '*4 + f'for slot in {tip_rack_slots}:\n')
                f.write(' '*8 + f'tip_racks.append(protocol.deck[slot])\n')
                f.write(' '*4 + f'pipette_{mount} = protocol.load_instrument(\'{pipette}\',\'{mount}\',tip_racks=tip_racks)\n')
                f.write(' '*4 + f'pipettes.append(pipette_{mount})\n')
                f.write(' '*4 + '\n')
            f.write('\n')


            dummy_protocol = []
            for slot,container in self.containers.items():
                action = PipetteAction(
                                source = f'{slot}A1',
                                dest   = f'{slot}A1',
                                volume = 250,
                                dest_loc = 'top'
                                
                    )
                dummy_protocol.append(action)

            for mount,(pipette,tip_rack_slots) in self.pipettes.items():
                for i,action in enumerate(dummy_protocol):
                    f.write(' '*4 + f'pipette = pipette_{mount}\n')
                    f.write(' '*4 + f'well_source = container_{action.source[0]}[\'{action.source[1:]}\']\n')
                    f.write(' '*4 + f'well_dest = container_{action.dest[0]}[\'{action.dest[1:]}\']\n')
                    f.write(' '*4 + f'pipette.transfer({action.volume},well_source,well_dest)\n')
                    f.write('\n')

                for slot,catch in self.catches.items():
                    f.write(' '*4 + f'pipette = pipette_{mount}\n')
                    f.write(' '*4 + f'well_source = container_{action.dest[0]}[\'{action.dest[1:]}\']\n')
                    f.write(' '*4 + f'well_dest = catch_{slot}[\'A1\']\n')
                    f.write(' '*4 + f'pipette.transfer({action.volume},well_source,well_dest)\n')
                    f.write('\n')

    def make_script(self,filename,load_last_sample=True):
        with open(filename,'w') as f:
            f.write('from opentrons import protocol_api\n')
            f.write('\n')
            f.write('\n')
            #f.write('metadata={\'apiLevel\':\'2.0\'}\n')
            f.write(metadata)
            f.write('\n')
            f.write('\n')
            f.write(get_pipette)
            f.write('\n')
            f.write('\n')
            f.write('def run(protocol):\n')

            
            f.write('\n')
            for slot,tiprack in self.tip_racks.items():
                f.write(' '*4+ f'tiprack_{slot} = protocol.load_labware(\'{tiprack}\',\'{slot}\')\n')
            f.write('\n')

            for slot,container in self.containers.items():
                f.write(' '*4 + f'container_{slot} = protocol.load_labware(\'{container}\',\'{slot}\')\n')
            f.write('\n')

            for slot,catch in self.catches.items():
                f.write(' '*4 + f'catch_{slot} = protocol.load_labware(\'{catch}\',\'{slot}\')\n')
            f.write('\n')

            f.write(' '*4 + 'pipettes = []\n')
            for mount,(pipette,tip_rack_slots) in self.pipettes.items():
                
                f.write(' '*4 + f'tip_racks = []\n')
                f.write(' '*4 + f'for slot in {tip_rack_slots}:\n')
                f.write(' '*8 + f'tip_racks.append(protocol.deck[slot])\n')
                f.write(' '*4 + f'pipette_{mount} = protocol.load_instrument(\'{pipette}\',\'{mount}\',tip_racks=tip_racks)\n')
                f.write(' '*4 + f'pipettes.append(pipette_{mount})\n')
                f.write(' '*4 + '\n')
            f.write('\n')

            if not self.protocol:
                return

            protocol = [action for action_group in self.protocol for action in action_group]
            for i,action in enumerate(protocol):
                f.write(' '*4 + f'pipette = get_pipette({action.volume},pipettes)\n')
                f.write(' '*4 + f'well_source = container_{action.source[0]}[\'{action.source[1:]}\']\n')
                f.write(' '*4 + f'well_dest = container_{action.dest[0]}[\'{action.dest[1:]}\']\n')
                f.write(' '*4 + f'pipette.transfer({action.volume},well_source,well_dest)\n')
                f.write('\n')
                if load_last_sample and (i == (len(self.protocol)-1)):
                    for slot,catch in self.catches.items():
                        f.write(' '*4 + f'pipette = get_pipette({action.volume},pipettes)\n')
                        f.write(' '*4 + f'well_source = container_{action.dest[0]}[\'{action.dest[1:]}\']\n')
                        f.write(' '*4 + f'well_dest = catch_{slot}[\'A1\']\n')
                        f.write(' '*4 + f'pipette.transfer({action.volume},well_source,well_dest)\n')
                        f.write('\n')

