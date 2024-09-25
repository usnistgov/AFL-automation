import os


try:
    if 'OT2' in open('/var/serial').read():
        # we are running on an OT2 and need to hack the path now
        print('we seem to be running on an OT-2; running path hacking')
        import sys
        sys.path.insert(0,f'/var/user-packages/root/.local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages/')
        import os
        os.environ['NISTOROBOTO_CUSTOM_LABWARE'] = '/root/custom_beta/'
        os.environ['RUNNING_ON_PI'] = '1'
        os.environ['OT_SMOOTHIE_ID'] = 'AMA'
except FileNotFoundError as e:
    pass    


from AFL.automation.prepare.ComponentDB import ComponentDB
db = ComponentDB()

from AFL.automation.prepare.Solute import Solute
from AFL.automation.prepare.Solution import Solution
from AFL.automation.prepare.Solvent import Solvent

from AFL.automation.prepare.Sample import Sample
from AFL.automation.prepare.SampleSeries import SampleSeries
from AFL.automation.prepare.Deck import Deck
from AFL.automation.prepare.utilities import make_locs,make_wellplate_locs

from AFL.automation.prepare.MassBalance import MassBalance
from AFL.automation.prepare.PipetteAction import PipetteAction

from AFL.automation.prepare.factory import compositionSweepFactory,HD2OFactory

