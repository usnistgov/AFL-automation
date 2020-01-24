import opentrons.execute
import opentrons

from NistoRoboto.shared.utilities import listify
from NistoRoboto.server.DoorDaemon import DoorDaemon

import threading
import time
import datetime

class RobotoDaemon(threading.Thread):
    '''
    '''
    def __init__(self,app,task_queue,debug_mode=True):
        app.logger.info('Creating RobotoDaemon thread')

        threading.Thread.__init__(self,daemon=True)

        self.protocol = opentrons.execute.get_protocol_api('2.0')
        self.doorDaemon = DoorDaemon(app,task_queue)
        self.doorDaemon.start()

        self._stop = False
        self._app = app
        self.task_queue = task_queue
        self.debug_mode = debug_mode

    def terminate(self):
        self.doorDaemon.terminate()

        self._app.logger.info('Terminating RobotoDaemon thread')
        self._stop = True
        self.task_queue.put(None)

    def reset(self):
        self._app.logger.info('Resetting the protocol context')
        self.protocol = opentrons.execute.get_protocol_api('2.0')

    def home(self):
        self._app.logger.info('Homing the robots axes')
        self.protocol.home()

    def run(self):
        while not self._stop:
            # this will block until something enters the task_queue
            task = self.task_queue.get(block=True,timeout=None)
            self._app.logger.info(f'Running task {task}')

            if task is None:
                self.terminate()
                break
            elif 'debug_mode' in task:
                self._app.logger.info(f'Setting queue debug_mode to {task["debug_mode"]}')
                self.debug_mode = task['debug_mode']
                continue
            elif self.debug_mode:
                time.sleep(2.0)
                continue

            # #interlock check
            # while self.doorDaemon.safe and abs(self.doorDaemon.last_check - datetime.now)<250:
            #     time.sleep(0.1)

            if task['type'] == 'transfer':
                self.transfer(**task)
            elif task['type'] == 'load_labware':
                self.load_labware(**task)
            elif task['type'] == 'load_instrument':
                self.load_instrument(**task)
            elif task['type'] == 'reset':
                self.reset()
            elif task['type'] == 'home':
                self.home()
            else:
                raise ValueError(f'Task type not recognized: {task["type"]}')
            time.sleep(0.1)

        self._app.logger.info('RobotoDaemon runloop exiting')

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

    def load_labware(self,name,slot,**kw):
        self.protocol.load_labware(name,slot)

    def load_instrument(self,name,mount,tip_rack_slots,**kw):
        tip_racks = []
        for slot in tip_rack_slots:
            tip_rack = self.protocol.deck[slot]
            if not tip_rack.is_tiprack:
                raise RuntimeError('Supplied slot doesn\'t contain a tip_rack!')
            tip_racks.append(tip_rack)
        self.protocol.load_instrument(name,mount,tip_racks=tip_racks)

    def transfer(self,source,dest,volume,**kwargs):
        '''Transfer fluid from one location to another

        Arguments
        ---------
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
        self._app.logger.info(f'Transfer {volume}uL from {source} to {dest}')

        #get pipette based on volume
        pipette = self.get_pipette(volume)
        source_wells = self.get_wells(source)
        dest_wells = self.get_wells(dest)
        pipette.transfer(volume,source_wells,dest_wells)

    def get_pipette(self,volume):
        found_pipettes = []
        minVolStr = ''
        for mount,pipette in self.protocol.loaded_instruments.items():
            minVolStr += f'{pipette.min_volume}>{volume}\\n'
            if volume>pipette.min_volume:
                found_pipettes.append(pipette)
    
        if not found_pipettes:
            raise ValueError('No suitable pipettes found!\\n'+ minVolStr)
        else:
            return min(found_pipettes,key=lambda x: x.max_volume)
    







