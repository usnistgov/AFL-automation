from AFL.automation.APIServer.Driver import Driver
from AFL.automation.APIServer.APIServer import APIServer
class SimpleDriver(Driver):
    defaults = {}
    defaults['greeting'] = 'Hello, World!'
    defaults['Number'] = 5

    def __init__(self, overrides=None):
        Driver.__init__(self, name='SimpleDriver',
                       defaults=self.gather_defaults(),
                       overrides=overrides)
    def say_hello(self):
        """Say a greeting based on configuration"""
        return self.config['greeting']
    def add_with(self, num):
        return num+self.config['Number']

if __name__ == '__main__':
    from AFL.automation.shared.launcher import *
