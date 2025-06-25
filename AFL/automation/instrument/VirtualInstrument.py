import time
import numpy as np
from AFL.automation.APIServer.Driver import Driver
from AFL.automation.instrument.ScatteringInstrument import ScatteringInstrument

class VirtualInstrument(ScatteringInstrument, Driver):
    defaults = {}
    defaults['image_shape'] = (128, 128)
    defaults['noise'] = 0.0
    defaults['exposure_delay'] = 0.0
    defaults['q_min'] = 1e-3
    defaults['q_max'] = 1.0

    def __init__(self, overrides=None):
        self.app = None
        Driver.__init__(self, name='VirtualInstrument',
                         defaults=self.gather_defaults(),
                         overrides=overrides)
        ScatteringInstrument.__init__(self)
        self.__instrument_name__ = 'Virtual Scattering Instrument'
        self.status_txt = 'Idle'

    def cell_in_beam(self, cellid):
        return True

    def expose(self, name=None, exposure=None, nexp=1, block=True,
               measure_transmission=True, save_nexus=True):
        delay = self.config.get('exposure_delay', 0) if exposure is None else exposure
        if delay > 0:
            time.sleep(delay)
        return self.getData()

    def measure(self, *args, **kwargs):
        img = self.expose(*args, **kwargs)
        npts = self.config['npts']
        intensity = np.random.random(npts)
        if self.data is not None:
            self.data.add_array('I', intensity)
        q_min = self.config['q_min']
        q_max = self.config['q_max']
        q = np.logspace(np.log10(q_min), np.log10(q_max), npts)
        if self.data is not None:
            self.data['q'] = q
        return intensity

    @Driver.unqueued(render_hint='2d_img', log_image=True)
    def getData(self, **kwargs):
        shape = self.config['image_shape']
        data = np.random.random(shape)
        noise = self.config['noise']
        if noise:
            data += np.random.normal(scale=noise, size=shape)
        return data

    def status(self):
        return [self.status_txt]
