import warnings
try:
    import nice
except ImportError:
    warnings.warn('NICE import failed- NICE instrument connections will not work.  Install nice.',stacklevel=2)
   
class NICEDevice(nice.api.devices.DevicesMonitor):
    def changed(self,changed,current):
        self.nodes.update(changed)
        self.current = current
        
    def onSubscribe(self,devices,nodes,staticNodeData,current):
        self.devices = devices
        self.nodes = nodes
        self.staticNodeData = staticNodeData
        self.current = current
