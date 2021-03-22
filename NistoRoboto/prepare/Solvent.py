from NistoRoboto.prepare.Component import Component
from NistoRoboto.prepare.PrepType import PrepType,prepRegistrar
from NistoRoboto.shared.units import enforce_units


@prepRegistrar(PrepType.Solvent)
class Solvent(Component):
    '''Specialization class for solute components '''
    def __init__(self,name,density,description=None,formula=None,sld=None):
        super().__init__(name,description)
        self.preptype = PrepType.Solvent
        self.density = density
        self.formula = formula
        self.sld = sld
        
    def __str__(self):
        out_str  = f'<Solvent '
        out_str += f'M={self.mass:4.3f} '
        out_str += f'V={self.volume:4.3f}'
        out_str += '>'
        return out_str
