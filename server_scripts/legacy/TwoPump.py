import os,sys,subprocess

try:
  import AFL.automation
except:
  sys.path.append('../')

server_port=5000

from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.loading.PushPullSelectorSampleCell import PushPullSelectorSampleCell
from AFL.automation.loading.NE1kSyringePump import NE1kSyringePump
from AFL.automation.loading.ViciMultiposSelector import ViciMultiposSelector
from AFL.automation.loading.Tubing import Tubing

selector1 = ViciMultiposSelector('/dev/ttyFlwSel0',
                                 baudrate=19200,
                                 portlabels={'catch':6,'catchBlack':7,'rinse':9,'waste':8,'air':10,
                                     # 'cell8':1,
                                     'cell5':2,
                                     'cell2':3,
                                     'cell4':4,
                                     'cell9':5,
                                     })

selector2 = ViciMultiposSelector('/dev/ttyFlwSel1',
                                 baudrate=19200,
                                 portlabels={'catch':6,'catchWhite':7,'rinse':9,'waste':8,'air':10,
                                     'cell3':1,
                                     'cell1':2,
                                     'cell7':3,
                                     # 'cell6':4,
                                     })

pump1 = NE1kSyringePump('/dev/ttySyrPmp0',14.86,10,baud=19200,pumpid=10) # ID for 10mL = 14.859, for 50 mL 26.43
pump2 = NE1kSyringePump('/dev/ttySyrPmp0',14.86,10,baud=19200,pumpid=11,daisy_chain=pump1) # ID for 10mL = 14.859, for 50 mL 26.43

driver1 = PushPullSelectorSampleCell(pump1,
                                      selector1,
                                      catch_to_sel_vol      =Tubing(1517,122).volume(),
                                      cell_to_sel_vol       =Tubing(1517,61).volume() + 0.5,
                                      syringe_to_sel_vol    =None,
                                      selector_internal_vol =None,
                                     )

server1 = APIServer('SampleCellServer1')
server1.add_standard_routes()
server1.create_queue(driver1)
server1.run_threaded(host='0.0.0.0',port=server_port, debug=False)

driver2 = PushPullSelectorSampleCell(pump2,
                                      selector2,
                                      catch_to_sel_vol      =Tubing(1517,182.9).volume(),
                                      cell_to_sel_vol       =Tubing(1517,91.4).volume() + 1.5,
                                      syringe_to_sel_vol    =None,
                                      selector_internal_vol =None,
                                     )

server2 = APIServer('SampleCellServer2')
server2.add_standard_routes()
server2.create_queue(driver2)
server2.run(host='0.0.0.0',port=5001, debug=False)

process = subprocess.Popen(f'chromium-browser --start-fullscreen http://localhost:{server_port}', shell=True, stdout=subprocess.PIPE)
process.wait()

server.stop()
server.join()

