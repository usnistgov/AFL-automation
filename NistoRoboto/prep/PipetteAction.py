class PipetteAction:
    def __init__(self,origin,destination,volume):
        self.origin       = origin
        self.destination = destination
        self.volume       = volume
    
    def __str__(self):
        return f'<PipetteAction Vol:{self.volume:4.3f} {self.origin}-->{self.destination}>'
    
    def __repr__(self):
        return self.__str__()
    
    def get_kwargs(self):
        kwargs = {}
        kwargs['origin'] = self.origin
        kwargs['destination'] = self.destination
        kwargs['volume'] = self.volume
        return kwargs
