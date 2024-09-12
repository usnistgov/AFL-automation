import time
import datetime
import pathlib
import warnings
import json
import copy
import os

import numpy as np  # for return types in get data
import h5py  # for Nexus file writing

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument.ScatteringInstrument import ScatteringInstrument

from nicos.clients.base import ConnectionData, NicosClient
from nicos.protocols.daemon import STATUS_IDLE, STATUS_IDLEEXC
from nicos.utils.loggers import ACTION, INPUT

#NICOS events to exclude from client
EVENTMASK = ('watch', 'datapoint', 'datacurve', 'clientexec')

class SINQSANS_NICOS(ScatteringInstrument, Driver):
    defaults = {}
    defaults['nicos_host'] = 'sans.psi.ch'
    defaults['nicos_port'] = 1301
    defaults['nicos_user'] = 'user'
    defaults['nicos_password'] = ''
    defaults['empty transmission'] = 1
    defaults['transmission strategy'] = 'sum'
    defaults['reduced_data_dir'] = ''
    defaults['exposure'] = 1.
    defaults['absolute_calibration_factor'] = 1
    defaults['data_path'] = ''

    defaults['detector'] = 'sansdet'
    defaults['detector_main_index'] = 0

    defaults['pixel1'] = 0.075  # pixel y size in m
    defaults['pixel2'] = 0.075  # pixel x size in m
    defaults['num_pixel1'] = 128
    defaults['num_pixel2'] = 128

    defaults['beamstop_in'] = -70 #bsy
    defaults['beamstop_out'] = -200 #bsy

    def __init__(self, overrides=None):

        self.app = None
        Driver.__init__(self, name='SINQSANS_NICOS', defaults=self.gather_defaults(), overrides=overrides)
        ScatteringInstrument.__init__(self)

        self.client = NicosClient_AFL()
        self.connect_to_nicos()

        if self.config['reduced_data_dir'] is not None:
            os.chdir(self.config['reduced_data_dir'])

        self.__instrument_name__ = 'PSI SINQ SANS instrument'

        self.status_txt = 'Just started...'
        self.last_measured_transmission = [0, 0, 0, 0]

    def connect_to_nicos(self):
        self.client.connect(
            host = self.config['nicos_host'],
            port = self.config['nicos_port'],
            user = self.config['nicos_user'],
            password = self.config['nicos_password'],
        )

    def pre_execute(self, **kwargs):
        pass

    def setReducedDataDir(self, path):
        self.config['reduced_data_dir'] = path
        os.chdir(path)


    def lastMeasuredTransmission(self):
        return self.last_measured_transmission

    @Driver.unqueued()
    def getExposure(self):
        ''' get the currently set exposure counts

        if using counts() NICOS command, this is the number of counts on a monitor

        if using counts2() NICOS command, this is the number of counts on the detector

        '''
        return self.config['exposure']

    @Driver.unqueued()
    def getLastFilename(self):
        """ get the currently set file name """

        scans = self.client.eval('session.experiment.data.getLastScans()', None)
        if not scans:
            raise ValueError('No scans returned.')

        return scans[-1].filenames[-1]


    @Driver.unqueued()
    def getLastFilePathLocal(self, **kwargs):
        ''' get the currently set file name '''

        filename = self.getLastFilename()
        filepath = pathlib.Path(self.config['data_path']) / filename
        if self.app is not None:
            self.app.logger.debug(f'Last file found to be {filepath}')
        else:
            print(f'Last file found to be {filepath}')
        return filepath

    def setExposure(self, exposure):
        if self.app is not None:
            self.app.logger.debug(f'Setting exposure time to {exposure}')
        self.config['exposure'] = exposure

    def setSample(self, name):
        name = name.replace('\\', '').replace('/', '').replace(':', '').replace('%', '')

        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        self.client.command(f'NewSample("{name}")')

    def getSample(self):
        name = self.client.eval('session.experiment.sample.samplename', None)
        return name

    def getElapsedTime(self):
        raise NotImplementedError

    def readH5(self, filepath, update_config=False, **kwargs):
        out_dict = {}
        with h5py.File(filepath, 'r') as h5:
            out_dict['counts'] = h5['entry1/data1/counts'][()]
            # out_dict['name']           = h5['entry1/sample/name'][()]
            # out_dict['dist']           = h5['entry1/SANS/detector/x_position'][()]/1000
            # out_dict['wavelength']     = h5['entry1/data1/lambda'][()]*1e-9,
            # out_dict['beam_center_x']  = h5['entry1/SANS/detector/beam_center_x'][()]
            # out_dict['beam_center_y']  = h5['entry1/SANS/detector/beam_center_y'][()]
            # out_dict['poni2']          = h5['entry1/SANS/detector/beam_center_x'][()]*self.config['pixel1']
            # out_dict['poni1 ']         = h5['entry1/SANS/detector/beam_center_y'][()]*self.config['pixel2']

        # if update_config:
        #     self.config['wavelength'] = out_dict['wavelength']
        #     self.config['dist']       = out_dict['dist']
        #     self.config['poni1']      = out_dict['poni1']
        #     self.config['poni2']      = out_dict['poni2']

        return out_dict

    @Driver.unqueued(render_hint='2d_img', log_image=True)
    def getData(self, **kwargs):
        try:
            filepath = self.getLastFilePathLocal()
            data = self.readH5(filepath)['counts']
        except (FileNotFoundError, OSError, KeyError):
            nattempts = 1
            while nattempts < 31:
                nattempts = nattempts + 1
                time.sleep(1.0)
                try:
                    filepath = self.getLastFilePathLocal()
                    data = self.readH5(filepath)['counts']
                except (FileNotFoundError, OSError, KeyError):
                    if nattempts == 30:
                        raise FileNotFoundError(f'Could not locate file {filepath} after {nattempts} tries')
                    else:
                        warnings.warn(f'Failed to load file {filepath}, trying again, this is try {nattempts}')
                else:
                    break

        return np.nan_to_num(data)


    def _simple_expose(self, exposure, name=None, block=False):
        if name is None:
            name = self.getSample()
        else:
            self.setSample(name)

        self.setExposure(exposure)

        self.status_txt = f'Starting {exposure} count named {name}'
        if self.app is not None:
            self.app.logger.debug(self.status_txt)

        self.client.command(f'count2({self.config["exposure"]})')

        if block:
            self.blockForIdle()

    @Driver.quickbar(qb={'button_text': 'Measure Transmission',
                         'params': {
                             'set_empty_transmission': {'label': 'Set Empty Trans?', 'type': 'boolean',
                                                        'default': False}
                         }})
    def measureTransmission(self, exposure=1e5, set_empty_transmission=False, return_full=False): 
        self.client.command(f'maw(shutter,"closed")')
        self.client.command(f'move(att,"1")')
        self.client.command(f'move(bsy,{self.config["beamstop_out"]})')
        self.client.command(f'wait()')
        self.client.command(f'maw(shutter,"open")')

        self._simple_expose(exposure=exposure, block=True) 

        self.client.command(f'maw(shutter,"closed")')
        self.client.command(f'move(bsy,{self.config["beamstop_in"]})')
        self.client.command(f'move(att,"0")')
        self.client.command(f'wait()')
        self.client.command(f'maw(shutter,"open")')

        cts = self.banana(xlo=40,xhi=80,ylo=40,yhi=80,measure=False)

        monitor_cts = self.client.val('monitor1')[0]

        trans = cts / monitor_cts #!!! add dead_time correction to monitor

        if set_empty_transmission:
            self.config['empty transmission'] = trans

        self.last_measured_transmission = (
            trans / self.config['empty transmission'],
            monitor_cts,
            cts,
            self.config['empty transmission']
        )

        if return_full:
            return self.last_measured_transmission
        else:
            return trans / self.config['empty transmission']


    @Driver.quickbar(qb={'button_text': 'Expose',
                         'params': {
                             'name': {'label': 'Name', 'type': 'text', 'default': 'test_exposure'},
                             'exposure': {'label': 'Exposure (s)', 'type': 'float', 'default': 5},
                             'reduce_data': {'label': 'Reduce?', 'type': 'bool', 'default': True},
                             'measure_transmission': {'label': 'Measure Trans?', 'type': 'bool', 'default': True}
                         }})
    def expose(self, name=None, exposure=None, exposure_transmission=None, block=True, reduce_data=True, measure_transmission=True,
               save_nexus=True):
        if name is None:
            name = self.getSample()
        else:
            self.setSample(name)

        if measure_transmission:
            self.measureTransmission(exposure=exposure_transmission)

        self._simple_expose(exposure=exposure, block=block)
        self.client.clear_queue()
        time.sleep(15)

        if reduce_data or save_nexus:

            data = self.getData()
            print(f"Loaded data with {data.sum()} total counts")
            if save_nexus:
                self.status_txt = 'Writing Nexus'
                normalized_sample_transmission = self.last_measured_transmission[0]
                if self.data is not None:
                    self.data['raw_data'] = data
                    self.data['normalized_sample_transmission'] = normalized_sample_transmission
                self._writeNexus(data, name, name, self.last_measured_transmission)

            if reduce_data:
                self.status_txt = 'Reducing Data'
                reduced = self.getReducedData(write_data=True, filename=name)
                if self.data is not None:
                    self.data['reduced_data'] = reduced
                np.savetxt(f'{name}_chosen_r1d.csv', np.transpose(reduced), delimiter=',')

                normalized_sample_transmission = self.last_measured_transmission[0]
                open_flux = self.last_measured_transmission[1]
                sample_flux = self.last_measured_transmission[2]
                empty_cell_transmission = self.last_measured_transmission[3]
                sample_transmission = normalized_sample_transmission * empty_cell_transmission

                if self.data is not None:
                    self.data['normalized_sample_transmission'] = normalized_sample_transmission
                    self.data['open_flux'] = open_flux
                    self.data['sample_flux'] = sample_flux
                    self.data['empty_cell_transmission'] = empty_cell_transmission
                    self.data['sample_transmission'] = sample_transmission

                if save_nexus:
                    self._appendReducedToNexus(reduced, name, name)

                out = {}
                out['normalized_sample_transmission'] = normalized_sample_transmission
                out['open_flux']                      = open_flux
                out['sample_flux']                    = sample_flux
                out['empty_cell_transmission']        = empty_cell_transmission
                out['sample_transmission'] = sample_transmission

                out = {k:float(v) for k,v in out.items()}
                with open(pathlib.Path(self.config['reduced_data_dir'])/f'{name}_trans.json', 'w') as f:
                    json.dump(out, f)

            self.status_txt = 'Instrument Idle'

    def blockForIdle(self, timeout=1800, initial_delay=5):
        time.sleep(initial_delay)

        notDone = True
        start = datetime.datetime.now()
        delta = datetime.timedelta(seconds=timeout)
        timedout = start + delta
        while notDone and (datetime.datetime.now() < timedout):
            notDone = (self.client.status!='idle')
            time.sleep(0.1)

    def banana(self,xlo=40,xhi=80,ylo=40,yhi=80,measure=True):
        """ Calculate a sum of data over a pixel range """
        if measure:
            self.client.command('count(m=1e3)')
            self.blockForIdle()
        arrays = self.client.livedata[self.config['detector']+'_live'] #return arrays from all detectors
        array  = arrays[self.config['detector_main_index']] #return selected detector array
        counts = array[xlo:xhi,ylo:yhi].sum()
        return counts

    def status(self):
        status = []
        status.append(
            f'Last Measured Transmission: scaled={self.last_measured_transmission[0]} using empty cell trans of {self.last_measured_transmission[3]} with {self.last_measured_transmission[1]} raw counts in open {self.last_measured_transmission[2]} sample')
        status.append(f'Status: {self.status_txt}')
        status.append(f'<a href="getData" target="_blank">Live Data (2D)</a>')
        status.append(f'<a href="getReducedData" target="_blank">Live Data (1D)</a>')
        status.append(f'<a href="getReducedData?render_hint=2d_img&reduce_type=2d">Live Data (2D, reduced)</a>')
        return status


class NicosClient_AFL(NicosClient):
    livedata = {}
    status = 'idle'

    def __init__(self):
        NicosClient.__init__(self, self.log)
        self.message_queue = []

    def signal(self, name, data=None, exc=None):
        accept = ['message', 'processing', 'done']
        if name in accept:
            self.log_func(name, data)
        elif name == 'livedata':
            converted_data = []
            for desc, ardata in zip(data['datadescs'], exc):
                npdata = np.frombuffer(ardata,
                                       dtype=desc['dtype'])
                npdata = npdata.reshape(desc['shape'])
                converted_data.append(npdata)
            self.livedata[data['det'] + '_live'] = converted_data
        elif name == 'status':
            status, _ = data
            if status == STATUS_IDLE or status == STATUS_IDLEEXC:
                self.status = 'idle'
            else:
                self.status = 'run'
        else:
            if name != 'cache':
                pass

    def log(self, name, txt):
        self.message_queue.append((name, txt))

    def print_queue(self):
        for msg in self.message_queue:
            print(f'{msg[0]}: {msg[1]}')
        self.message_queue = []

    def clear_queue(self):
        self.message_queue = []

    def connect(self, host, port, user, password):
        con = ConnectionData(host, port, user, password)

        NicosClient.connect(self, con, EVENTMASK)
        if self.daemon_info.get('protocol_version') < 22:
            raise RuntimeError("incompatible nicos server")

        state = self.ask('getstatus')
        self.signal('status', state['status'])
        self.print_queue()
        if self.isconnected:
            print('Successfully connected to %s' % host)
        else:
            print('Failed to connect to %s' % host)

    def command(self, line):
        com = "%s" % line.strip()
        run_uid = self.run(com)
        return run_uid

    def _command(self, line):
        com = "%s" % line.strip()
        if self.status == 'idle':
            self.run(com)
            return com
        return None

    def interactive(self, line):
        """
        Command is a bit fraught as it doesn't always catch the start signal, i.e., the processing flag

        If you're running into an error, switch to run

        Note that you'll want to clear the message queue periodically if not using 'command'

        """
        start_detected = False
        ignore = [ACTION, INPUT]
        reqID = None
        testcom = self._command(line)
        if not testcom:
            return 'NICOS is busy, cannot send commands'
        while True:
            if self.message_queue:
                # own copy for thread safety
                work_queue = copy.deepcopy(self.message_queue)
                self.message_queue = []
                for name, message in work_queue:
                    #print(f'COMMAND: NAME={name} MESSAGE={message}')
                    if name == 'processing':
                        if message['script'] == testcom:
                            start_detected = True
                            reqID = message['reqid']
                        continue
                    if name == 'done' and message['reqid'] == reqID:
                        return
                    if message[2] in ignore:
                        continue
                    if message[0] != 'nicos':
                        messagetxt = message[0] + ' ' + message[3]
                    else:
                        messagetxt = message[3]
                    if start_detected and reqID == message[-1]:
                        print(messagetxt.strip())

    def val(self, parameter):
        """
        This can be implemented on top of the client.devValue()
        and devParamValue() interfaces. The problem to be solved is
        how to make the data visible in ipython
        """
        # check for livedata first
        if parameter in self.livedata:
            return self.livedata[parameter]

        # Now check for scan data
        if parameter == 'scandata':
            xs, ys, _, names = self.eval(
                '__import__("nicos").commands.analyze._getData()[:4]')
            return xs, ys, names

        # Try get device data from NICOS
        if parameter.find('.') > 0:
            devpar = parameter.split('.')
            return self.getDeviceParam(devpar[0], devpar[1])
        else:
            return self.getDeviceValue(parameter)

_DEFAULT_PORT=5001

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
