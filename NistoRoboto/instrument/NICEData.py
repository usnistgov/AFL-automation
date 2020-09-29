import nice

class NICEData(nice.api.data.DataMonitor):
    def onSubscribe(self,records,fits,current):
        self.records = records
        self.fits = fits
        
