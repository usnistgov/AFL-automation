from AFL.automation.APIServer import Driver
import json



class XArmManipulator(Driver):
    def transfer(self,src,dest):
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
                speed = self._arm_move_speed,
                mvacc = self._arm_move_accel,
                radius = -1.0,
                wait=True)
        if code: 
            raise Exception('Move failed!')
        else:
            return code

    def _get_loc_from_name(self,location):
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
        deck_kw = name[:-3]
        slot = name[-3]
        well = name[-2:]

        deck_base_location = self.config['deck_calibration'][0]
        deck_filename = self.config['deck_calibration'][1]

        with open(self.config['deck_dir'] +'/' + deck_filename + '.json') as f:
            deck_def = json.load(f)
            
        slot_offset = deck_def[slot]['postion_offset']

        with 
        

        location = [sum(x) for x in zip(deck_base_location, slot_offset, well_offset)]
        return location + [180.0,0.0,0.0]
