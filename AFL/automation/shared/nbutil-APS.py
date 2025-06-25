'''
helpful imports, object setup, etc. for working with AFL-automation from a Jupyter notebook or other interactive environment.
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
import warnings

import AFL.automation
import AFL.automation.prepare
from AFL.automation import prepare
from AFL.automation.APIServer.Client import Client
from AFL.automation.prepare.OT2Client import OT2Client
from AFL.automation.shared.exceptions import MixingException
from AFL.automation.shared.units import units
from collections import defaultdict
from itertools import cycle

# some handy functions to use along widgets
from IPython.display import display, Markdown, clear_output
# widget packages
import ipywidgets as widgets
import functools


import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--noclients',action='store_true')
parser.add_argument('--noui',action='store_true')
args = parser.parse_args()
    
if not args.noclients:
    try:
        prep = OT2Client(ip='piot2',interactive=True)
        prep.login('RobotoStation')
        prep.debug(False)
    except requests.ConnectionError as e:
        warnings.warn('Failed to connect to OT2 server.')
    
    try:
        inst = Client(ip='localhost',port='5000',interactive=True)
        inst.login('RobotoStation')
        inst.debug(False)
    except requests.ConnectionError as e:
        warnings.warn('Failed to connect to APSUSAXS server.')
    
    try:
        load = Client('piloader',interactive=True)
        load.login('RobotoStation')
        load.debug(False)
    except requests.ConnectionError as e:
        warnings.warn('Failed to connect to loader server.')


    try:
        sample = Client(ip='localhost',port='5000',interactive=True)
        sample.login('RobotoStation')
        sample.debug(False)
    except requests.ConnectionError as e:
        warnings.warn('Failed to connect to sample server.')
    
    sample_client = sample
    

class NRUI:
    def homerobot(caller):
        prep.home()
    def refilltips(caller):
        prep.reset_tipracks()
    def transfer(caller):
        prep.transfer(NRUI.widgets['src'].value,NRUI.widgets['dest'].value,NRUI.widgets['vol'].value)
    def rinseCell(caller):
        load.enqueue(task_name='rinseCell',interactive=False)
    def blowCell(caller):
        load.enqueue(task_name='blowOutCell',interactive=False)
    def rinseCatch(caller):
        load.enqueue(task_name='rinseCatch',interactive=False)        
    def rinseSyringe(caller):
        load.enqueue(task_name='rinseSyringe',interactive=False)     
    def loadSample(caller):
        load.enqueue(task_name='loadSample',sampleVolume=NRUI.widgets['volume'].value,interactive=False)
        
    def measureEmptyTrans(caller):
        inst.enqueue(task_name='measureTransmission',set_empty_transmission=True,interactive=False)
    def measureTrans(caller):
        inst.enqueue(task_name='measureTransmission',interactive=False)        
    def measureSample(caller):
            inst.enqueue(task_name='expose',
                         name=NRUI.widgets['samplename'].value,
                         exposure=NRUI.widgets['exposure'].value,
                         measure_transmission=NRUI.widgets['doTransmission'].value,
                         interactive=False)
NRUI.tabs = {}
NRUI.tabs['robot'] = []
NRUI.tabs['loader'] = []
NRUI.tabs['cdsaxs'] = []

NRUI.widgets = {}
NRUI.widgets['home'] = widgets.Button(description='Home')
NRUI.widgets['home'].on_click(NRUI.homerobot)
NRUI.tabs['robot'].append(NRUI.widgets['home'])

NRUI.widgets['refill'] = widgets.Button(description='Refill Tipracks')
NRUI.widgets['refill'].on_click(NRUI.refilltips)
NRUI.tabs['robot'].append(NRUI.widgets['refill'])

NRUI.widgets['src'] = widgets.Text(
    value='1A1',
    description='Source:',
    disabled=False
)
NRUI.widgets['dest'] = widgets.Text(
    value='1A1',
    description='Destination:',
    disabled=False
)
NRUI.widgets['vol'] = widgets.FloatText(
    value='0.0',
    description='Volume (uL):',
    disabled=False
)
NRUI.widgets['xfer'] = widgets.Button(description='Transfer')
NRUI.widgets['xfer'].on_click(NRUI.transfer)#functools.partial(dummyfunc,task_name='test')) #prep.transfer)
NRUI.tabs['robot'].append(widgets.VBox([NRUI.widgets['src'],NRUI.widgets['dest'],NRUI.widgets['vol'],NRUI.widgets['xfer']]))

NRUI.widgets['rinsecell'] = widgets.Button(description='Rinse Cell')
NRUI.widgets['rinsecell'].on_click(NRUI.rinseCell)
NRUI.tabs['loader'].append(NRUI.widgets['rinsecell'])


NRUI.widgets['blowcell'] = widgets.Button(description='Blow Out Cell')
NRUI.widgets['blowcell'].on_click(NRUI.blowCell)
NRUI.tabs['loader'].append(NRUI.widgets['blowcell'])

NRUI.widgets['rinsecatch'] = widgets.Button(description='Rinse Catch')
NRUI.widgets['rinsecatch'].on_click(NRUI.rinseCatch)
NRUI.tabs['loader'].append(NRUI.widgets['rinsecatch'])

NRUI.widgets['rinsesyringe'] = widgets.Button(description='Rinse Syringe')
NRUI.widgets['rinsesyringe'].on_click(NRUI.rinseSyringe)
NRUI.tabs['loader'].append(NRUI.widgets['rinsesyringe'])

NRUI.widgets['volume'] = widgets.FloatText(
    value='0.0',
    description='Volume (mL):',
    disabled=False
)
NRUI.widgets['load'] = widgets.Button(description='Load Sample')
NRUI.widgets['load'].on_click(NRUI.loadSample)
NRUI.tabs['loader'].append(widgets.VBox([NRUI.widgets['volume'],NRUI.widgets['load']]))



NRUI.widgets['measureempty'] = widgets.Button(description='Measure Empty Cell Transmission')
NRUI.widgets['measureempty'].on_click(NRUI.measureEmptyTrans)
NRUI.tabs['cdsaxs'].append(NRUI.widgets['measureempty'])

NRUI.widgets['measuretrans'] = widgets.Button(description='Measure Transmission')
NRUI.widgets['measuretrans'].on_click(NRUI.measureTrans)
NRUI.tabs['cdsaxs'].append(NRUI.widgets['measuretrans'])

NRUI.widgets['samplename'] = widgets.Text(
    value='test-sample',
    description='Sample Name:',
    disabled=False
)
NRUI.widgets['exposure'] = widgets.FloatText(
    value='1',
    description='Exposure Time (s):',
    disabled=False
)

NRUI.widgets['doTransmission'] = widgets.Checkbox(
    value=True,
    description='Measure transmission? (will move sample)',
    disabled=False,
    indent=True
)

NRUI.widgets['measure'] = widgets.Button(description='Measure Sample')
NRUI.widgets['measure'].on_click(NRUI.measureSample)
NRUI.tabs['cdsaxs'].append(widgets.VBox([NRUI.widgets['samplename'],NRUI.widgets['exposure'],NRUI.widgets['doTransmission'],NRUI.widgets['measure']]))


NRUI.robot = widgets.HBox(NRUI.tabs['robot'])
NRUI.loader = widgets.HBox(NRUI.tabs['loader'])
NRUI.cdsaxs = widgets.HBox(NRUI.tabs['cdsaxs'])

NRUI.tab = widgets.Tab()
# setting the tab windows 
NRUI.tab.children = [NRUI.robot,NRUI.loader,NRUI.cdsaxs]
# changing the title of the first and second window
NRUI.tab.set_title(0, 'Robot')
NRUI.tab.set_title(1, 'Loader')
NRUI.tab.set_title(2, 'CDSAXS')
  
    
print('''

Welcome to AFL-automation's notebook interface!!

--> Server clients are set up in interactive mode and named prep, inst, load, and sample.

--> Component, Mixture, Deck, Client, OT2Client, make_locs, units, types, PipetteAction are imported from NR.

--> Normal scientific python tools are imported (np, plt, etc.).

--> AFL utility functions such as measureEmptyTransmission and calibrateLoadertoCell are created.

--> Finally, if you are connected to the system, you get a GUI!

Have a lot of fun!

''')

if (not args.noclients) and (not args.noui):
    display(NRUI.tab)
