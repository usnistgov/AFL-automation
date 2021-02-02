from collections import defaultdict
from NistoRoboto.prep.Mixture import Mixture

class SampleSeries:
    def __init__(self):
        self.reset()

    def reset(self):
        self.validated = []
        self.samples = []

    def __str__(self):
        nsamples = len(self.samples)
        nvalidated = sum(self.validated)
        out_str = f'<SampleSeries count:{nsamples} validated:{nvalidated}>'
        return out_str

    def __repr__(self):
        return self.__str__()

    def __iter__(self):
        for sample,validated in zip(self.samples,self.validated):
            yield sample,validated

    def add_sample(self,sample):
        self.samples.append(sample)
        self.validated.append(False)

    def mass_totals_stock(self,only_validated=True):
        mass_totals = defaultdict(float)
        for sample,validated in zip(self.samples,self.validated):
            if only_validated and (not validated):
                continue
                
            for stock,(loc,mass) in sample.mass_transfers.items():
                mass_totals[loc] += mass
        return mass_totals

    def mass_totals_component(self,only_validated=True):
        mass_totals = defaultdict(float)
        mixture = Mixture([])
        for sample,validated in zip(self.samples,self.validated):
            if only_validated and (not validated):
                continue
            mixture = mixture + sample.target_check
        return {name:component.mass for name,component  in mixture}

