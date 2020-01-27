class PipetteAction:
    def __init__(self,source,dest,volume,source_loc=None,dest_loc=None):
        self.source       = source
        self.dest         = dest
        self.volume       = volume
        self.source_loc   = source_loc
        self.dest_loc     = dest_loc
    
    def __str__(self):
        return f'<PipetteAction Vol:{self.volume:4.3f} {self.source}-->{self.dest}>'
    
    def __repr__(self):
        return self.__str__()
    
    def get_kwargs(self):
        kwargs = {}
        kwargs['source'] = self.source
        kwargs['dest'] = self.dest
        kwargs['volume'] = self.volume

        if self.source_loc is not None:
            kwargs['source_loc'] = self.source_loc

        if self.dest_loc is not None:
            kwargs['dest_loc'] = self.dest_loc


        return kwargs
