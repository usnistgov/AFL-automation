'''
helpful imports, object setup, etc. for working with NistoRoboto from a Jupyter notebook or other interactive environment.
'''

import sys
import numpy as np 
import ipywidgets
import matplotlib.pyplot as plt
import requests
import datetime
import time
import json
import copy
import random

import NistoRoboto
from NistoRoboto.prep.Component import Component
from NistoRoboto.prep.Mixture import Mixture
from NistoRoboto.prep.Deck import Deck
from NistoRoboto.APIServer.client.Client import Client
from NistoRoboto.APIServer.client.OT2Client import OT2Client
from NistoRoboto.shared.utilities import tprint
from NistoRoboto.shared.exceptions import MixingException
from NistoRoboto.prep.util import make_locs
from NistoRoboto.shared.units import units
from NistoRoboto.prep.types import types
from NistoRoboto.prep.PipetteAction import PipetteAction
from collections import defaultdict
from itertools import cycle

import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--noclients',action='store_true')
args = parser.parse_args()
    
if not args.noclients:
    prep = OT2Client(interactive=True)
    prep.login('RobotoStation')
    prep.debug(False)
    
    inst = Client(ip='cdsaxs',port='5000',interactive=True)
    inst.login('RobotoStation')
    inst.debug(False)
    
    load = Client('piloader2',interactive=True)
    load.login('RobotoStation')
    load.debug(False)


    sample = Client(ip='localhost',port='5000',interactive=True)
    sample.login('RobotoStation')
    sample.debug(False)

def measureEmptyTransmission():
    load.enqueue(task_name='rinseCell',interactive=True)
    load.enqueue(task_name='blowOutCell',interactive=True)
    inst.enqueue(task_name='measureTransmission',set_empty_transmission=True,interactive=True)

def calibrateLoaderToCell():
    a = input('Manually load 300 uL of strongly absorbing sample with comparable viscosity to your experiment into the catch.  Press any key to confirm sample is loaded.')
    upper = float(input('Enter an upper bound for the transfer volume loader-cell (mL)'))
    step = float(input('Enter the desired step size (mL)'))
    lower = float(input('Enter a lower bound for the transfer volume loader-cell (mL)') )

    #withdraw the larger of the syringe-to-loader volume OR the
    vol_air=0
    vol_catch=upper
    load.enqueue(device='selector',
                 task_name='selectPort',
                 port='air',
                 interactive=True)
    load.enqueue(device='pump',
                 task_name='withdraw',
                 volume=vol_air,
                 interactive=True)
    load.enqueue(device='selector',
                 task_name='selectPort',
                 port='catch',
                 interactive=True)
    load.enqueue(device='pump',
                 task_name='withdraw',
                 volume=vol_catch,
                 interactive=True)
    load.enqueue(device='selector',
                 task_name='selectPort',
                 port='cell',
                 interactive=True)
    trans = inst.enqueue(task_name='measureTransmissionQuick',
                setup=True)
    load.enqueue(device='pump',
                 task_name='dispense',
                 volume=lower,
                 interactive=True)
    vol_remaining = upper - lower
    data = []
    data.append([vol_remaining,trans])
    print(f'    @{vol_remaining}, trans={trans}')
    while vol_remaining>0:
        load.enqueue(device='pump',
                 task_name='dispense',
                 volume=step,
                 interactive=True)
        vol_remaining -= step
        trans = inst.enqueue(task_name='measureTransmissionQuick')
        print(f'    @{vol_remaining}, trans={trans}')
        data.append([vol_remaining,trans])
        
    trans = inst.enqueue(task_name='measureTransmissionQuick',
                        cleanup=True)
    data.append([vol_remaining,trans])
    print(f'    @{vol_remaining}, trans={trans}')
    print('Scan complete')
    return data

print('''

Welcome to NistoRoboto's notebook interface!!

--> Server clients are set up in interactive mode and named prep, inst, load, and sample.

--> Component, Mixture, Deck, Client, OT2Client, make_locs, units, types, PipetteAction are imported from NR.

--> Normal scientific python tools are imported (np, plt, etc.).

--> NistoRoboto utility functions such as measureEmptyTransmission and calibrateLoadertoCell are created.

Have a lot of fun!

''')
