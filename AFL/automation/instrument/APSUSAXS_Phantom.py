import time
import numpy as np
import xarray as xr
from AFL.automation.instrument.APSUSAXS import APSUSAXS
from AFL.automation.APIServer.Driver import Driver

class APSUSAXS_Phantom(APSUSAXS):
    def __init__(self, overrides=None):
        # We bypass APSUSAXS.__init__ to avoid any hardware initialization it might do
        # (though currently it seems mostly safe, it loads Matilda which we might not want)
        
        # Driver.__init__ will call gather_defaults which walks MRO.
        # So we get APSUSAXS.defaults automatically.
        self.app = None
        Driver.__init__(self, name='APSUSAXS_Phantom', defaults=self.gather_defaults(), overrides=overrides)
        
        self.__instrument_name__ = 'APS USAXS Phantom Instrument'
        
        self.status_txt = 'Phantom Initialized'
        self.filename = 'default'
        self.filename_prefix = 'AFL'
        self.project = 'AFL'
        self.xpos = 0
        self.ypos = 0
        
        self._run_in_progress = False

    def _writeUSAXSScript(self):
        pass

    def _safe_read_file(self, filepath, filename, is_usaxs=True, is_blank=False):
        pass

    @Driver.quickbar(qb={'button_text':'Expose Phantom',
        'params':{
        'name':{'label':'Name','type':'text','default':'test_exposure'},
        'exposure':{'label':'Exposure (s)','type':'float','default':5},
        'reduce_data':{'label':'Reduce?','type':'bool','default':True},
        'measure_transmission':{'label':'Measure Trans?','type':'bool','default':True}
        }})
    def expose(self, name=None, block=True, read_USAXS=True, read_SAXS=True, **kwargs):
        if name is None:
            name = self.getFilenamePrefix()
        else:
            self.setFilenamePrefix(name)
            
        self.status_txt = f'Starting Phantom USAXS/SAXS/WAXS scan named {name}'
        if self.app is not None:
            self.app.logger.debug(f'Starting Phantom exposure {name}')
            
        self._run_in_progress = True
        self.status_txt = 'Phantom Running...'
        
        # Simulate exposure time
        # Use exposure from kwargs if available, default to 1s
        exposure = float(kwargs.get('exposure', 1.0))
        time.sleep(exposure) 
        
        self._run_in_progress = False
        self.status_txt = 'Instrument Idle'
        
        if "blank" in name.lower():
            is_blank = True
        else:
            is_blank = False
            
        # Generate fake data
        # USAXS q range approx 1e-4 to 1e-1
        # SAXS q range approx 1e-2 to 1.0
        
        ds = xr.Dataset()
        ds.attrs['USAXS_Filepath'] = '/tmp/phantom/usaxs'
        ds.attrs['USAXS_Filename'] = f'{name}.h5'
        ds.attrs['USAXS_name'] = name
        ds.attrs['USAXS_blank'] = is_blank
        if read_USAXS:
            q_usaxs = np.logspace(np.log10(1e-4), np.log10(1e-1), 200)
            I_usaxs, dI_usaxs = self._generate_fake_signal(q_usaxs, is_blank)
            ds['USAXS_q'] = ('USAXS_q',q_usaxs)
            ds['USAXS_I'] = ('USAXS_q',I_usaxs)
            ds['USAXS_dI'] = ('USAXS_q',dI_usaxs)
            

        if read_SAXS:
            q_saxs = np.logspace(np.log10(1e-2), np.log10(1.0), 200)
            I_saxs, dI_saxs = self._generate_fake_signal(q_saxs, is_blank)
            if ds is None:
                ds = xr.Dataset()

            ds['SAXS_q'] = ('SAXS_q',q_saxs)
            ds['SAXS_I'] = ('SAXS_q',I_saxs)
            ds['SAXS_dI'] = ('SAXS_q',dI_saxs)

        return ds

    def _generate_fake_signal(self, q, is_blank):
        if is_blank:
            # White noise around low value
            I = np.random.normal(1e-4, 1e-5, size=q.shape)
            I = np.abs(I)
        else:
            # Simple scattering model: Guinier + Power law + Background
            # Parameters
            Rg = 50.0   # Radius of gyration
            I0 = 100.0  # Forward scattering
            P = 4.0     # Power law slope (Porod)
            B = 1e-3    # Background
            
            # Unified fit-ish
            # Guinier term
            I_guinier = I0 * np.exp(-(q * Rg)**2 / 3.0)
            
            # Power law term (with cutoff to avoid singularity)
            # Using simple crossover
            q_crossover = 1.0/Rg
            I_porod = (I0 * np.exp(-1/3)) * ((q/q_crossover)**(-P))
            
            # Smooth combine (very approximate)
            I_signal = np.where(q < q_crossover, I_guinier, I_porod)
            
            I = I_signal + B + np.random.normal(0, 1e-4, size=q.shape)
            I = np.abs(I)
            
        dI = 0.05 * I # 5% error
        return I, dI

    def block_for_run_finish(self):
        while self.getRunInProgress():
            time.sleep(0.1)

    def getRunStatus(self):
        return "Phantom Running" if self._run_in_progress else "Phantom Idle"

    def getRunInProgress(self):
        return self._run_in_progress
        
    def setPosition(self, plate, row, col, x_offset=0, y_offset=0):
        # Calculate coordinates using parent method logic but update local state
        (self.xpos, self.ypos) = self._coords_from_tuple(plate, row, col)
        self.xpos += x_offset
        self.ypos += y_offset
        if self.app is not None:
            self.app.logger.debug(f'Phantom: Position set to {self.xpos}, {self.ypos}')

    def status(self):
        status = []
        status.append(f'Status: {self.status_txt}')
        status.append(f'Phantom Status: {self.getRunStatus()}')
        status.append(f'Next X: {self.xpos}')
        status.append(f'Next Y: {self.ypos}')
        status.append(f'Next filename: {self.filename}')
        status.append(f'Next project: {self.project}')
        return status

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
    # This allows the file to be run directly to start a server for this driver


