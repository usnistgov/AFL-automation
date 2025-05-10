import lazy_loader as lazy
# NIST NCNR NICE control system
nice = lazy.load("nice", require="AFL-automation[nice-neutron-scattering]")

class NICEData(nice.api.data.DataMonitor):
    def onSubscribe(self,records,fits,current):
        self.records = records
        self.fits = fits
        
