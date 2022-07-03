class PipetteAction:
    def __init__(self,
            source,
            dest,
            volume,
            source_loc=None,
            dest_loc=None,
            aspirate_rate=None,
            dispense_rate=None,
            mix_aspirate_rate=None,
            mix_dispense_rate=None,
            mix_before = None,
            mix_after = None,
            blow_out = False,
            post_aspirate_delay=0.0,
            post_dispense_delay=0.0,
            drop_tip=True,
            force_new_tip=False,
            ):
        self.kwargs ={}
        self.kwargs['source']       = source
        self.kwargs['dest']         = dest
        self.kwargs['volume']       = volume
        self.kwargs['source_loc']   = source_loc
        self.kwargs['dest_loc']     = dest_loc
        self.kwargs['mix_before']   = mix_before
        self.kwargs['mix_after']    = mix_after
        self.kwargs['aspirate_rate'] = aspirate_rate
        self.kwargs['dispense_rate'] = dispense_rate
        self.kwargs['mix_aspirate_rate'] = mix_aspirate_rate
        self.kwargs['mix_dispense_rate'] = mix_dispense_rate
        self.kwargs['blow_out'] = blow_out
        self.kwargs['post_aspirate_delay'] = post_aspirate_delay
        self.kwargs['post_dispense_delay'] = post_dispense_delay
        self.kwargs['drop_tip'] = drop_tip
        self.kwargs['force_new_tip'] = force_new_tip
    
    def __str__(self):
        return f'<PipetteAction Vol:{self.volume:4.3f} {self.source}-->{self.dest}>'
    
    def __repr__(self):
        return self.__str__()

    def emit_protocol(self):
        return self.get_kwargs()
    
    def get_kwargs(self):
        if self.kwargs['source_loc'] is None:
            del self.kwargs['source_loc']
        if self.kwargs['dest_loc'] is None:
            del self.kwargs['dest_loc']
        return self.kwargs
