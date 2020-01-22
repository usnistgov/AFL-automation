class Deck:
    def __init__(self):
        self.stocks        = []
        self.targets       = []
        self.stock_location = {}
        self.target_location = {}
        
        self.components        = set()
        self.components_stock  = set()
        self.components_target = set()
        
        self.protocol = []

        self.containers    = {}
        self.pipettes      = {}
        
    def add_pipette(self,name,mount,tipracks):
        if not (mount in ['left','right']):
            raise ValueError('Pipette mount point can only be "left" or "right"')

        tiprack__list = []
        for slot,name in tipracks:
            self.tipracks[slot] = name
            tipack_list.append(f'tiprack_{slot}')

        self.pipettes[mount] = name,tiprack_list

    def add_container(self,name,slot):
        self.containers[slot] = name

    def get_pipette_by_volume(self,volume):
        for mount,pipette
        
    def generate_script(self,filename):
        with open(filename,'w') as f:
            f.write('from opentrons import protocol_api\n')
            f.write('\n')
            f.write('\n')
            f.write('metadata={\'apiLevel\':\'2.0\'}\n')
            f.write('\n')
            f.write('\n')
            f.write('''
            def get_pipette(volume,loaded_pipettes):
                found_pipettes = []
                for pipette in loaded_pipettes:
                    if ((volume>pipette.min) and (volume<pipette.max))
                        found_pipettes.append(pipette)

                if not found_pipettes:
                    raise ValueError('No suitable pipettes found!')
                else:
                    return min(pipettes,key=lambda x: x.max_volume)
            ''')
            f.write('\n')
            f.write('\n')
            f.write('''
            def get_well(loc):
                found_pipettes = []
                for pipette in loaded_pipettes:
                    if ((volume>pipette.min) and (volume<pipette.max))
                        found_pipettes.append(pipette)

                if not found_pipettes:
                    raise ValueError('No suitable pipettes found!')
                else:
                    return min(pipettes,key=lambda x: x.max_volume)
            ''')
            f.write('\n')
            f.write('\n')
            f.write('def run(protocol):\n')

            for slot,tiprack in self.tipracks.items():
                f.write(f'\ttiprack_{slot} = protocol.load_labware(\'{tiprack}\',\'{slot}\')\n')
            f.write('\n')

            container_list = []
            for slot,container in self.container.items():
                f.write(f'\tcontainer_{slot} = protocol.load_labware(\'{container}\',\'{slot}\')\n')
                container_list.append(f'container_{slot}\n')
            f.write('\n')

            f.write('\tpipettes = []')
            for mount,(pipettte,tip_racks) in self.container.items():
                f.write(f'pipette_{mount} = protocol.load_labware(\'{pipette}\',\'{slot}\',tip_racks=[{tip_racks}])\n')
                f.write(f'pipettes.append(pipette_{mount})\n')
            f.write('\n')

            if not self.protocol:
                return

            for action in self.protocol:
                f.write(f'pipette = get_pipette({action.volume},pipettes)\n')
                f.write(f'well_source = container_{action.source[0]}[action.source[1:]])\n')
                f.write(f'well_dest = container_{action.dest[0]}[action.dest[1:]])\n')
                f.write(f'pipette.transfer({action.volume},{well_source},{well_dest})\n')
                f.write('\n')



    def add_stock(self,stock,location):
        stock = stock.copy()
        self.stocks.append(stock)
        self.stock_location[stock] = location
        
        for name,component in stock:
            self.components.add(name)
            self.components_stock.add(name)
            
    def add_target(self,target,location):
        target = target.copy()
        self.targets.append(target)
        self.target_location[target] = location
        
        for name,component in target:
            self.components.add(name)
            self.components_target.add(name)
            
    def create_protocol(self):
        for target in self.targets:
            
            # build matrix and vector representing mass balance
            mass_fraction_matrix = []
            target_component_masses = []
            for name in self.components:
                row = []
                for stock in self.stocks:
                    if name in stock.components:
                        if stock[name]._has_mass:
                            row.append(stock.mass_fraction[name])
                        else:
                            raise ValueError('Need masses specified for mass balance')
                    else:
                        row.append(0)
                mass_fraction_matrix.append(row)
                
                if name in target.components:
                    if target[name]._has_mass:
                        target_component_masses.append(target[name].mass)
                    else:
                        raise ValueError('Need masses specified for mass balance')
                else:
                    target_component_masses.append(0)

            #solve mass balance 
            mass_transfers,residuals,rank,singularity = np.linalg.lstsq(mass_fraction_matrix,target_component_masses)
            
            #apply mass balance
            target_check = Mixture()
            for stock,mass in zip(self.stocks,mass_transfers):
                if mass>0:
                    removed = stock.remove_mass(mass)
                    target_check = target_check + removed
                    
                    action = PipetteAction(
                                source = self.stock_location[stock],
                                dest = self.target_location[target],
                                volume = removed.volume
                                
                    )
                    self.protocol.append(action)
                    
            if not (target == target_check):
                raise RuntimeError('Mass transfer calculation failed...')

