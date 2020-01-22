import opentrons.execute
import opentrons

from NistoRoboto.shared.utilities import listify

import threading
import time
from opentrons.drivers.rpi_drivers import gpio


class DoorDaemon(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self._stop = False
        self._open = True
        opentrons.robot._driver.turn_off_button_light()

    def is_open(self):
        return self._open

    def terminate(self):
        self._stop = True

    def run(self):
        print('--> Running DoorDaemon!')
        while not self._stop:
            if gpio.read_window_switches():
                gpio.set_button_light(green=True,red=False,blue=False)
                self._open=False
            else:
                gpio.set_button_light(green=False,red=True,blue=False)
                self._open=True
            time.sleep(1)



class Server:
    '''
    '''
    def __init__(self):
        self.protocol = opentrons.execute.get_protocol_api('2.0')
        self.doorDaemon = DoorDaemon()
        self.doorDaemon.start()

    def get_wells(self,locs):
        wells = []
        for loc in listify(locs):
            if not (len(loc) == 3):
                raise ValueError(f'Well specification should be [SLOT][ROW_LETTER][COL_NUM] not {loc}')
            slot = loc[0]
            well = loc[1:]
            labware = self.get_labware(slot)
            wells.append(labware[well])
        return wells

    def get_labware(self,slot):
        if self.protocol.deck[slot] is not None:
            return self.protocol.deck[slot]
        else:
            raise ValueError('Specified slot ({slot}) is empty of labware')

    def transfer(self,mount,source,dest,volume,**kwargs):
        '''Transfer fluid from one location to another

        Arguments
        ---------
        mount: str ('left' or 'right')
            Mount location of pipette to be used

        source: str or list of str
            Source wells to transfer from. Wells should be specified as three
            character strings with the first character being the slot number.

        dest: str or list of str
            Destination wells to transfer from. Wells should be specified as
            three character strings with the first character being the slot
            number.

        volume: float
            volume of fluid to transfer

        '''

        #get pipette
        pipette = self.protocol.loaded_instruments[mount]
        source_wells = self.get_wells(source)
        dest_wells = self.get_wells(dest)
        pipette.transfer(volume,source,dest)








