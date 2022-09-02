class Sample:
    def __init__(self,name,target,target_check=None,balancer=None):
        self.target = target
        self.name = name
        self.protocol=[]

        if target_check is not None:
            self.target_check = target_check
        else:
            self._target_check = None

        if balancer is not None:
            self.balancer = balancer
        else:
            self._balancer = None

    def __str__(self):
        out_str = f'<Sample name:{self.name}>'
        return out_str

    def __repr__(self):
        return self.__str__()
    
    def emit_protocol(self):
        return [p.emit_protocol() for p in self.protocol]

    @property
    def target(self):
        return self._target
    
    @target.setter
    def target(self,value):
        self._target = value.copy()

    @property
    def target_check(self):
        return self._target_check
    
    @target_check.setter
    def target_check(self,value):
        self._target_check = value.copy()

    @property
    def balancer(self):
        return self._balancer
    
    @balancer.setter
    def balancer(self,value):
        self._balancer = value.copy()

    @property
    def target_loc(self):
        return self.balancer.target_location
