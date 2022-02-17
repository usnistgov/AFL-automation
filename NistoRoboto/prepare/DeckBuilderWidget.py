import numpy as np
import pandas as pd
import xarray as xr
from math import sqrt

import plotly.graph_objects as go
import plotly.express as px

import ipywidgets
from ipywidgets import Dropdown,Layout,Label,Button,Checkbox,VBox,HBox,Text
import pickle

import NistoRoboto.prepare 
from NistoRoboto.shared.units import units

class DeckBuilderWidget:
    def __init__(self):
        self.data_model = DeckBuilderWidget_Model()
        self.data_view = DeckBuilderWidget_View()
        
    def start(self):
        widget = self.data_view.start()
        return widget
        
class DeckBuilderWidget_Model:
    pass

class DeckBuilderWidget_View:
    def __init__(self):
        self.pipette_list = ['p300_single','p1000_single_gen2']
        self.container_list = [
            'nist_6_20ml_vials',
            'nist_2_100ml_poly_bottle',
            'nest_96_wellplate_1600ul'
        ]
        self.catch_list = ['nist_1_10ml_syringeloader']
        self.tipracks_list = ['opentrons_96_tiprack_300ul','opentrons_96_tiprack_1000ul']
        self.deckware_types = ['container','tips','catch']
        self.deckware_list = ['empty']+self.container_list+self.tipracks_list+self.catch_list
    def create_expanded_button(self,description, button_style):
        return Button(description=description, button_style=button_style, layout=Layout(height='auto', width='auto'))
    def draw_deck(self):
        self.deck = ipywidgets.GridspecLayout(4, 3, height='300px',width='300px')
        
        location = 1
        self.deck_map = {}
        for i in reversed(range(4)):
            for j in range(3):
                if (i==0) and (j==2):
                    continue
                self.deck[i,j] = self.create_expanded_button(f'{location}', 'success')
                #self.deck[i,j].style.button_color='gray'
                self.deck_map[location] = (i,j)
                location+=1
        return self.deck
    
    
    def start(self):
        deck = self.draw_deck()
        
        self.deckware_dropdowns = {}
        self.deckware_groups = {}
        deckware_control_groups = []
        for i in range(1,12):
            dropdown = Dropdown(description=f"Slot {i}:",options=self.deckware_list)
            self.deckware_dropdowns[i] = dropdown
            deckware_control_group = HBox([dropdown],layout={'padding-bottom':'5px'})
            
            self.deckware_groups[i] = deckware_control_group
            deckware_control_groups.append(deckware_control_group)
            
        self.pipette_left_dropdown = Dropdown(description="Pipette Left:",options=self.pipette_list)
        
        self.pipette_right_dropdown = Dropdown(description="Pipette Right:",options=self.pipette_list)
            
        vbox1 = VBox([deck,self.pipette_left_dropdown,self.pipette_right_dropdown])
        vbox2 = VBox(deckware_control_groups) 
        hbox_deck = HBox([vbox1,vbox2])
        
        self.saveload_deck_label = Label("Filepath:")
        self.saveload_deck_input = Text(value="./deck.pkl")
        self.save_deck_button = Button(description="Save Deck")
        self.load_deck_button = Button(description="Load Deck")
        hbox_saveload = HBox([
            self.saveload_deck_label,
            self.saveload_deck_input,
            self.save_deck_button,
            self.load_deck_button
        ])
        
        self.sync_deck_label = Label(value="OT2 IP:")
        self.sync_deck_input = Text(value="piot2")
        self.sync_deck_button = Button(description="Sync Deck")
        hbox_sync = HBox([
            self.sync_deck_label,
            self.sync_deck_input,
            self.sync_deck_button,
        ])
        vbox = VBox([hbox_deck,hbox_saveload,hbox_sync])
        
        return vbox
    