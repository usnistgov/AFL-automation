from enum import Enum,auto
from NistoRoboto.shared.utilities import makeRegistar

class PrepType(Enum):
    BaseComponent=auto()
    BaseMixture=auto()
    Solute=auto()
    Solvent=auto()
    Solution=auto()


# Registrar decorator for prepType classes
prepRegistrar = makeRegistar()

