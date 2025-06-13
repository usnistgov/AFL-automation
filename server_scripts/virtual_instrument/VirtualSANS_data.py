import os,sys,subprocess
from pathlib import Path
try:
        import AFL.automation
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')
import xarray as xr
from AFL.automation.APIServer.APIServer import APIServer
from AFL.automation.instrument.virtual_sans_data import VirtualSANS_data
from AFL.automation.APIServer.data.DataTiled import DataTiled

### local tiled server here
data = DataTiled(server='http://0.0.0.0:8000', api_key = os.environ['TILED_API_KEY'], backup_path='/Users/drs18/.afl/json-backup')
server = APIServer('VirtualSANS_Data_Server',index_template='index.html', data=data)


### afl tiled server
#data = DataTiled('http://afl-inst-lab.campus.nist.gov:8000',api_key = os.environ['TILED_API_KEY'],backup_path='/Users/pab2/.afl/json-backup')
#server = APIServer('DummyPumpServer',index_template="index_pump.html",data = data)


server.add_standard_routes()

#should add an argparser here to point to the input dataset
#add method to server that adds the datafile

### to instantiate the dataset, do so in the notebook
#ds_path = '/Users/drs18/Documents/multimodal-dev/sinq_data_manifests/230530_AL_manifest-P188_2D_MultiModal_UCB_noThomp_FixedP188.nc'
#model_ds = xr.load_dataset(ds_path)
#client.set_object(dataset=model_ds)


server.create_queue(VirtualSANS_data())


server.init_logging()

#does this port need to be soemthing special?
server.run(host='0.0.0.0', port=5054)#, debug=True)
