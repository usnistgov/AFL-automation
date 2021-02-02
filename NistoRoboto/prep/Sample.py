
class Sample:
    def __init__(self,target,target_check=None,balancer=None):
        self.target = target

        if target_check is not None:
            self.target_check = target_check
        else:
            self._target_check = None

        if balancer is not None:
            self.balancer = balancer
        else:
            self._balancer = None

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
