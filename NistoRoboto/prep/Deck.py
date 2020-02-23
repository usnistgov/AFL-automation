import numpy as np
from NistoRoboto.prep.Mixture import Mixture
from NistoRoboto.prep.PipetteAction import PipetteAction
from NistoRoboto.shared.exceptions import MixingException

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
        
        self.protocol = []

        self.tip_racks    = {}
        self.containers    = {}
        self.pipettes      = {}
        self.catches = {}

        self.client = None

    def init_remote_connection(self,url,home=False):
        from NistoRoboto.DeviceServer.OT2Client import OT2Client
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


    def make_protocol(self,deplete=True,volume_cutoff=0.03):
        #build component list
        components,target_components,stock_components = self.get_components()
        self.protocol = []
        for target in self.targets:
            
            # build matrix and vector representing mass balance
            mass_fraction_matrix = []
            target_component_masses = []
            for name in components:
                row = []
                for stock in self.stocks:
                    if name in stock.components:
                        if stock[name]._has_mass:
                            row.append(stock.mass_fraction[name])
                        elif stock[name].empty:
                            row.append(0) #this component is set to zero
                        else:
                            raise ValueError('Need masses specified for mass balance')
                    else:
                        row.append(0)
                mass_fraction_matrix.append(row)
                
                if name in target.components:
                    if target[name]._has_mass:
                        target_component_masses.append(target[name].mass)
                    elif target[name].empty:
                        target_component_masses.append(0.0) #this component is set to zero
                    else:
                        raise ValueError('Need masses specified for mass balance')
                else:
                    target_component_masses.append(0)

            #solve mass balance 
            mass_transfers,residuals,rank,singularity = np.linalg.lstsq(mass_fraction_matrix,target_component_masses,rcond=-1)
            self.mass_transfers = mass_transfers
           
            #
            for stock,mass in zip(self.stocks,mass_transfers):
                if mass>0:
                    removed = stock.copy()
                    removed.mass = mass
                    if (removed.volume>0) and (removed.volume<volume_cutoff):
                        raise MixingException('Can\'t make solution with loaded pipettes')

            #apply mass balance
            self.target_check = Mixture()
            for stock,mass in zip(self.stocks,mass_transfers):
                if mass>0:
                    if deplete:
                        removed = stock.remove_mass(mass)
                    else:
                        removed = stock.copy()
                        removed.mass = mass

                    #check to make sure that min_tol hasn't been hit
                    if not (removed.volume>0):
                        continue

                    self.target_check = self.target_check + removed
                    
                    action = PipetteAction(
                                source = self.stock_location[stock],
                                dest = self.target_location[target],
                                volume = removed.volume*1000, #convet from ml for to ul
                                dest_loc = 'top'
                                
                    )
                    self.protocol.append(action)

            #need to add empty components for equality check
            for name,component in target:
                if component.empty:
                    self.target_check = self.target_check + component
                    
            if not (target == self.target_check):
                raise RuntimeError('Mass transfer calculation failed...')

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

            for i,action in enumerate(self.protocol):
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

