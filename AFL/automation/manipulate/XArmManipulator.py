from AFL.automation.APIServer.Driver import Driver
import json,copy,os,re


class XArmManipulator(Driver):
    '''
        A class to control the XArm manipulator
    '''
    overrides = {
    }
    defaults = {
        'arm_move_speed':100.0,
        'arm_move_accel':2000.0,
        'arm_move_delay': 2.0,
        'deck_def_dir': '~/.afl/deck_defs/',
        'labware_def_dir': '~/.afl/labware_defs/',
        'location_map_template': {'deck':{
            'base':[0,0,0],
            'name': 'AFL 8 position deck',
            'def' : 'afl_8pos_deck.json'
        },  
        'spin':{
            'base': [0,0,0],
            'name': 'AFL spincoater',
            'def' : 'afl_spincoater.json'
        }}

    }
    def __init__(self,overrides={}):
        self._app = None

        Driver.__init__(self,name='XArmManipulator',defaults=self.gather_defaults(),overrides=overrides)

        self._location_map = self._prepare_location_map()
    def _prepare_location_map(self):
        locmap = copy.deepcopy(self.config['location_map_template'])
        for key in locmap.keys():
            with open(os.path.expanduser(self.config['deck_def_dir']) + locmap[key]['def']) as f:
                locmap[key].update(json.load(f))
        return locmap
    def load_labware(self,deck,slot,filename):
        '''
            deck: str, name of the deck to load labware onto
            slot: str, slot on the deck to load labware into
            filename: str, name of the labware definition in opentrons format
                a corresponding .json file must be present in the config 'labware_def_dir'
                  '''
        slot = str(slot)

        with open(os.path.expanduser(self.config['labware_def_dir']) + filename + '.json') as f:
            labware_def = json.load(f)
        self._location_map[deck][slot].update(labware_def)


    def clear_labware(self,deck,slot):
        '''
            deck: str, name of the deck to clear labware from
            slot: str, slot on the deck to clear labware from
        '''
        slot = str(slot)
        keys_to_del = []
        for key in self._location_map[deck][slot].keys():
            if key not in ['base','name','def','offset']:
                keys_to_del += [key]
        for key in keys_to_del:
            del self._location_map[deck][slot][key]


    def transfer(self,src,dest):
        '''
            Transfer an object from one location to another

            src: str, name of the source location
            dest: str, name of the destination location
        '''
        self.move(src,above=True)
        self.move(src,above=False)
        self.vacuum(True)
        self.move(src,above=True)
        self.move(dest,above=True)
        self.move(dest,above=False)
        self.vacuum(False)
        self.move(dest,above=True)
        self.move('home')

    def vacuum(self,state):
        code = self.arm.set_suction_cup(on=state,wait=True)
        if code:
            raise Exception('Pickup/drop failed!')
        else:
            return code
    def move(self,location,above):
        loc = self._get_loc_from_name(location)
        if above:
            loc[2] = loc[2] + self._clearance_height
        code = self.arm.set_position(*loc, 
                speed = self.config['arm_move_speed'],
                mvacc = self.config['arm_move_accel'],
                radius = -1.0,
                wait=True)
        if code: 
            raise Exception('Move failed!')
        else:
            return code

    def _parse_name(self,name):
        '''
            return a dict with keys:
                'deck': str, name of the deck
                'slot': str, slot on the deck
                'well': str, well in the slot
            example names: 'deck1A1','spin1A1','deck1H12','deckB1H12'

        '''
        target = name
        match_patterns = ['\w*?','[\d]','[\D]','\d+']
        out_vals = []
        while len(match_patterns)>0:
            match_string = ''
            for token in match_patterns:
                match_string += token
            out_vals.append(re.split(match_string,target)[0])
            del(match_patterns[0])
            target = target.replace(out_vals[-1],'',1)
        out_vals.append(target)

        return {'deck':out_vals[1],'slot':out_vals[2],'well':out_vals[3]+out_vals[4]}
    def _get_loc_from_name(self,name):
        '''
            return a list [x,y,z,rx,ry,rz] from a location name
            name takes the format 'deck1A3', where:
                name[-2:] is the labware slot number and resolves a 
                labware position offset
                name[-3] is the deck slot number and resolves a deck
                position offset.
                name[:-3] is the keyword for the deck and resolves a
                coordinate set in config.

            self.config['deck_calibration'] is a dict with schema:
                str(name): [
                            base_position (list [x,y,z]),
                            deck_typedef (str matching a json)]
        '''
        loc = self._parse_name(name)
        deck_kw = loc['deck']
        slot = loc['slot']
        well = loc['well']

        deck_base_location = self._location_map[deck_kw]['base']
        deck_def = self._location_map[deck_kw]['def']
        slot_offset = self._location_map[deck_kw][slot]['offset']
        try:
            well_offset = [
                    self._location_map[deck_kw][slot]['wells'][well]['x'],
                    self._location_map[deck_kw][slot]['wells'][well]['y'],
                    self._location_map[deck_kw][slot]['wells'][well]['z']
                    ]
        except KeyError as e:
            raise Exception(f'Well {well} not found in slot {slot}')

        location = [sum(x) for x in zip(deck_base_location, slot_offset, well_offset)]
        return location + [180.0,0.0,0.0]
