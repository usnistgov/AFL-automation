class PipetteAction:
    def __init__(self,origin,destination,volume):
        self.source       = source
        self.dest         = destination
        self.volume       = volume
    
    def __str__(self):
        return f'<PipetteAction Vol:{self.volume:4.3f} {self.source}-->{self.dest}>'
    
    def __repr__(self):
        return self.__str__()
    
    def get_kwargs(self):
        kwargs = {}
        kwargs['source'] = self.source
        kwargs['dest'] = self.dest
        kwargs['volume'] = self.volume
        return kwargs
