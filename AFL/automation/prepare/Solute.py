from AFL.automation.prepare.Component import Component
from AFL.automation.prepare.PrepType import PrepType,prepRegistrar
from AFL.automation.shared.units import enforce_units


@prepRegistrar(PrepType.Solute)
class Solute(Component):
    '''Specialization class for solute components '''
    def __init__(self,name,description=None,density=None,formula=None,sld=None):
        super().__init__(name,description)
        self.preptype = PrepType.Solute
        self.density = density
        self.formula = formula
        self.sld = sld
        
    def __str__(self):
        out_str  = f'<Solute M={self.mass:4.3f}>'
        return out_str
        
    @property
    def volume(self):
        return None
    
    @volume.setter
    def volume(self,value):
        raise ArgumentError('Solute cannot have volume')

    def set_volume(self,volume):
        '''Setter for inline volume changes'''
        raise ArgumentError('Solute cannot have volume')
        
    
