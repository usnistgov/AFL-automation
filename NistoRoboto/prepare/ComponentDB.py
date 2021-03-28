import pathlib
import json
from NistoRoboto.prepare.PrepType import PrepType,prepRegistrar
from NistoRoboto.shared.units import units,AVOGADROS_NUMBER

from NistoRoboto.shared.exceptions import NotFoundError
from NistoRoboto.prepare.utilities import componentFactory

def _process_NoneType_string(value,mapping=lambda x: x):
    return  (None if value.lower()=='none' else mapping(value))

class ComponentDB:
    def __init__(self,path='.nistoroboto/component.db.json'):
        self.path = pathlib.Path.home()/pathlib.Path(path)
        
        if self.path.exists():
            self.read()
        else:
            self.db = {}

    def __str__(self):
        out_str = f'<ComponentDB path:{self.path} size:{len(self.db)}>'
        return out_str

    def __repr__(self):
        return self.__str__()

    def read(self,path=None):
        if path is not None:
            self.path = pathlib.Path.home()/pathlib.Path(path)
        with open(self.path,'r') as f:
            self.db = json.load(f)
            
    def write(self,path=None):
        if path is not None:
            self.path = pathlib.Path.home()/pathlib.Path(path)
        with open(self.path,'w') as f:
            json.dump(self.db,f,indent=4)
        
    def add(self,name,preptype,formula=None,density=None,sld=None,write=False,description=None,overwrite=False):
        if (not overwrite) and (name in self.db):
            raise ValueError(f'{name} already exists in database!') from None
            
        self.db[name] = {
            'name':str(name),
            'formula':str(formula),
            'density':str(density),
            'preptype':str(preptype),
            'sld':str(sld),
            'description':str(description),
        }
        if write:
            self.write()
            
    def add_interactive(self,name):
        resp = input(f'==> Attempting to add {name} to ComponentDB, continue? [yes]:')
        if resp.lower() in ['n','no','nope']:
            raise ValueError('Interactive add failed...') from None
        
        description = input('--> Description of Component?:').strip()
        
        resp = input('--> PrepType: Solvent or Solute? [solvent]:').strip().lower()
        if resp == 'solvent':
            preptype = PrepType.Solvent
        elif resp == 'solute':
            preptype = PrepType.Solute
        elif not resp: #empty string, default to solute
            preptype = PrepType.Solute
        else:
            raise ValueError(f'PrepType {resp.lower()} not recognized') from None
        
        resp = input('--> Empirical formula? [None]:').strip()
        if not resp:
            formula = None
        else:
            formula = resp
            
        resp1 = input('--> Density? [None]:').strip().lower()
        resp2 = input('--> Density units? [g/ml]:').strip()
        if not resp1:
            density = None
        elif not resp2:
            density = float(resp1)*units('g/ml')
        else:
            density = float(resp1)*units(resp2)
            
        resp = input('--> SLD? [None]:').strip().lower()
        if not resp:
            sld = None
        else:
            sld = float(resp)*10e-6*units('angstrom^(-2)')
            
        resp = input('~~> Save updated db? [yes]:').strip().lower()
        if not resp:
            write = True
        elif resp in ['yes','y']:
            write = True
        else:
            write = False
            
        
        self.add(
            name=name,
            preptype=preptype,
            formula=formula,
            density=density,
            sld=sld,
            write=write,
            description=description
        )
        
    def remove(self,name,write=False):
        del self.db[name]
        if write:
            self.write()
            
    def __getitem__(self,name):
        try:
            entry = self.db[name]
        except KeyError:
            raise NotFoundError(f'{name} not found in component database') from None
        
        #this should maybe some sort of dict
        preptype = PrepType[entry['preptype'].split('.')[1]]
            
        component = componentFactory( 
            preptype = preptype,
            name    = name,
            density =  _process_NoneType_string(entry['density'],units),
            formula =  _process_NoneType_string(entry['formula']),
            sld =  _process_NoneType_string(entry['sld']),
            description = _process_NoneType_string(entry['description'])
        )
        
        return component
        
    
    
    
