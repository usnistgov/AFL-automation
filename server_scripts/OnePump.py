import os
from NistoRoboto.DeviceServer.DeviceServer import DeviceServer

from NistoRoboto.loading.PushPullSelectorSampleCell import PushPullSelectorSampleCell
from NistoRoboto.loading.NE1kSyringePump import NE1kSyringePump
from NistoRoboto.loading.ViciMultiposSelector import ViciMultiposSelector
from NistoRoboto.loading.Tubing import Tubing

selector = ViciMultiposSelector(
        '/dev/ttyFlwSel0',
        baudrate=19200,
        portlabels={
            'catch':1,
            'cell':5,
            'waste':8,
            'rinse':9,
            'air':10,
            }
        )
pump = NE1kSyringePump('/dev/ttySyrPmp0',14.86,10,baud=19200,pumpid=10) # ID for 10mL = 14.859, for 50 mL 26.43
protocol = PushPullSelectorSampleCell(pump,
                                      selector,
                                      catch_to_sel_vol      =Tubing(1517,112).volume(),
                                      cell_to_sel_vol       =Tubing(1517,170).volume(),
                                      syringe_to_sel_vol    =None,
                                      selector_internal_vol =None,
                                     )


server = DeviceServer('SampleCellServer1')
server.add_standard_routes()
server.create_queue(protocol)
server.run(host='0.0.0.0',port=5000, debug=False)
