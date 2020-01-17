

class ScatteringInstrument():

    def __init__(self,exposuretime=1,thickness=1,nexp=1):
            self.exposuretime = exposuretime
            self.thickness = thickness
            self.nexp = nexp

    def cell_in_beam(self,cellid):

        raise NotImplementedError

    def expose(self,exposuretime,nexp):

        raise NotImplementedError

    




