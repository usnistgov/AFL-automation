import os,sys,subprocess
from pathlib import Path

try:
        import NistoRoboto
except:
        sys.path.append(os.path.abspath(Path(__file__).parent.parent))
        print(f'Could not find NistoRoboto on system path, adding {os.path.abspath(Path(__file__).parent.parent)} to PYTHONPATH')



from NistoRoboto import componentDB

try: 
        import componentDB.component
except:
        sys.path.append(os.path.abspath(Path(__file__).parent))

app = componentDB.create_app()

app.run(port=5123,debug=True)
