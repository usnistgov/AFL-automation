from AFL.automation.mixing.Context import Context

class MassBalance(Context):
    def __init__(self,name='MassBalance'):
        super().__init__(name=name)
        self.context_type = 'Deck'
        self.stocks = []

    def __call__(self,reset=False):
        if reset:
            self.stocks.clear()
        return self
