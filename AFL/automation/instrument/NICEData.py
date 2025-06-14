import warnings
try:
    import nice
except ImportError:
    warnings.warn('NICE import failed- NICE instrument connections will not work.  Install nice.',stacklevel=2)
   
class NICEData(nice.api.data.DataMonitor):
    def onSubscribe(self,records,fits,current):
        self.records = records
        self.fits = fits
        
