class PipetteAction:
    def __init__(self,
            source,
            dest,
            volume,
            source_loc=None,
            dest_loc=None,
            aspirate_rate=None,
            dispense_rate=None,
            mix_before = None,
            blow_out = False,
            ):
        self.source       = source
        self.dest         = dest
        self.volume       = volume
        self.source_loc   = source_loc
        self.dest_loc     = dest_loc
        self.mix_before   = mix_before
        self.aspirate_rate = aspirate_rate
        self.dispense_rate = dispense_rate
        self.blow_out = blow_out
    
    def __str__(self):
        return f'<PipetteAction Vol:{self.volume:4.3f} {self.source}-->{self.dest}>'
    
    def __repr__(self):
        return self.__str__()
    
    def get_kwargs(self):
        kwargs = {}
        kwargs['source'] = self.source
        kwargs['dest'] = self.dest
        kwargs['volume'] = self.volume
        kwargs['mix_before'] = self.mix_before
        kwargs['blow_out'] = self.blow_out

        if self.source_loc is not None:
            kwargs['source_loc'] = self.source_loc

        if self.dest_loc is not None:
            kwargs['dest_loc'] = self.dest_loc

        kwargs['aspirate_rate']=self.aspirate_rate
        kwargs['dispense_rate']=self.dispense_rate

        return kwargs
