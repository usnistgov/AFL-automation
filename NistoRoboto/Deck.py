class Deck:
    def __init__(self):
        self.stocks        = []
        self.targets       = []
        self.containers    = {}
        self.stock_location = {}
        self.target_location = {}
        
        self.components        = set()
        self.components_stock  = set()
        self.components_target = set()
        
        self.strategy = []
        
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
            
    def create_transfer_strategy(self):
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
                                origin = self.stock_location[stock],
                                destination = self.target_location[target],
                                volume = removed.volume
                                
                    )
                    self.strategy.append(action)
                    
            if not (target == target_check):
                raise RuntimeError('Mass transfer calculation failed...')
