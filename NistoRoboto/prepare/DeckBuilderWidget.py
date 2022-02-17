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
        
    def build_deck_object(self):
        config = self.get_deck_config()
        deck = self.data_model.build_deck_object(config)
        return deck 
    def get_deck_config(self):
        containers = {}
        catches = {}
        tipracks = {
            'all':{},
            'left_list':[],
            'right_list':[],
            'left':self.data_view.pipette_left_tips_dropdown.value,
            'right':self.data_view.pipette_right_tips_dropdown.value,
        }
        pipettes = {
            'left':self.data_view.pipette_left_dropdown.value,
            'right':self.data_view.pipette_right_dropdown.value,
        }
        for slot,dropdown in self.data_view.deckware_dropdowns.items():
            value = dropdown.value
            if value == 'empty':
                continue
                
            if value in self.data_view.container_list:
                containers[slot] = value
            elif value in self.data_view.tipracks_list:
                tipracks['all'][slot] = value
                if value == self.data_view.pipette_left_tips_dropdown.value:
                    tipracks['left_list'].append((slot,value))
                elif value == self.data_view.pipette_right_tips_dropdown.value:
                    tipracks['right_list'].append((slot,value))
            elif value in self.data_view.catch_list:
                catches[slot]  = value
        deck = {'containers':containers,'tipracks':tipracks,'catches':catches,'pipettes':pipettes}
        return deck
    
    def set_deck_config(self,config):
        for slot,value in config['containers'].items():
            self.data_view.deckware_dropdowns[slot].value = value
            
        for slot,value in config['catches'].items():
            self.data_view.deckware_dropdowns[slot].value = value
            
        for slot,value in config['tipracks']['all'].items():
            self.data_view.deckware_dropdowns[slot].value = value
            
        for slot,value in config['tipracks']['right_list']:
            self.data_view.deckware_dropdowns[slot].value = value
            
        left_value = config['tipracks']['left']
        right_value = config['tipracks']['right']
        self.data_view.pipette_left_tips_dropdown.value = left_value
        self.data_view.pipette_right_tips_dropdown.value = right_value
    
        left_value = config['pipettes']['left']
        right_value = config['pipettes']['right']
        self.data_view.pipette_left_dropdown.value = left_value
        self.data_view.pipette_right_dropdown.value = right_value
    
    def save_cb(self,event):
        config = self.get_deck_config()
        filename = self.data_view.saveload_deck_input.value
        with open(filename,'wb') as f:
            pickle.dump(config,f)
            
    def load_cb(self,event):
        filename = self.data_view.saveload_deck_input.value
        with open(filename,'rb') as f:
            config = pickle.load(f)
        self.set_deck_config(config)
        
    def update_deck_graphic_cb(self,event):
        for slot,dropdown in self.data_view.deckware_dropdowns.items():
            value = dropdown.value
            deck_location = self.data_view.deck_map[slot]
            if value == 'empty':
                self.data_view.deck[deck_location].style.button_color='gray'
            elif value in self.data_view.container_list:
                self.data_view.deck[deck_location].style.button_color='blue'
            elif value in self.data_view.tipracks_list:
                self.data_view.deck[deck_location].style.button_color='green'
            elif value in self.data_view.catch_list:
                self.data_view.deck[deck_location].style.button_color='red'
        
    def start(self):
        widget = self.data_view.start()
        for slot,dropdown in self.data_view.deckware_dropdowns.items():
            dropdown.observe(self.update_deck_graphic_cb,names=['value'])
        
        self.data_view.save_deck_button.on_click(self.save_cb)
        self.data_view.load_deck_button.on_click(self.load_cb)
        return widget
        
class DeckBuilderWidget_Model:
    def __init__(self):
        self.deck = None
        
    def send_deck_config(self,pi_ip='piot2',align_script='/home/nistoroboto/align.py'):
        if self.deck is None:
            raise ValueError('Can\'t send config without building deck object!')
        
        self.deck.make_align_script()
        self.deck.init_remote_connection(pi_ip)
        self.deck.send_deck_config()
    
    def build_deck_object(self,config):
        self.deck = NistoRoboto.prepare.Deck()
        for slot,value in config['containers'].items():
            self.deck.add_container(value,slot)
            
        for slot,value in config['catches'].items():
            self.deck.add_catch(value,slot)
            
        tipracks = config['tipracks']['left_list']
        pipette_left = config['pipettes']['left']
        self.deck.add_pipette(pipette_left,'left',tipracks=tipracks)
        
        tipracks = config['tipracks']['right_list']
        pipette_right = config['pipettes']['right']
        self.deck.add_pipette(pipette_right,'right',tipracks=tipracks)
        return self.deck
            

class DeckBuilderWidget_View:
    def __init__(self):
        self.pipette_list = ['p300_single','p1000_single_gen2']
        self.container_list = [
            'nist_6_20ml_vials',
            'nist_2_100ml_poly_bottle',
            'nest_96_wellplate_1600ul'
        ]
        self.catch_list = [
            'nist_pneumatic_loader', 
            'nist_stirred_catch',
            'nist_1_10ml_syringeloader',
        ]
        self.tipracks_list = ['opentrons_96_tiprack_300ul','opentrons_96_tiprack_1000ul']
        self.deckware_types = ['container','tips','catch']
        self.deckware_list = ['empty']+self.container_list+self.tipracks_list+self.catch_list
        
    def create_expanded_button(self,description, button_style):
        return Button(description=description, button_style=button_style, layout=Layout(height='auto', width='auto'))
    def draw_deck(self):
        self.deck = ipywidgets.GridspecLayout(4, 3, height='400px',width='400px')
        
        location = 1
        self.deck_map = {}
        for i in reversed(range(4)):
            for j in range(3):
                if (i==0) and (j==2):
                    continue
                self.deck[i,j] = self.create_expanded_button(f'{location}', 'success')
                self.deck[i,j].style.button_color='gray'
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
        self.pipette_left_tips_dropdown = Dropdown(description="Left Tips",options=self.tipracks_list)
        
        self.pipette_right_dropdown = Dropdown(description="Pipette Right:",options=self.pipette_list)
        self.pipette_right_tips_dropdown = Dropdown(description="Right Tips",options=self.tipracks_list)
        deckware_control_groups.append(self.pipette_left_dropdown)
        deckware_control_groups.append(self.pipette_left_tips_dropdown)
        deckware_control_groups.append(self.pipette_right_dropdown)
        deckware_control_groups.append(self.pipette_right_tips_dropdown)
        
            
        vbox1 = VBox([deck])
        vbox2 = VBox(deckware_control_groups) 
        vbox3 = VBox([
            # self.pipette_left_dropdown,
            # self.pipette_left_tips_dropdown,
            #self.pipette_right_dropdown,
            #self.pipette_right_tips_dropdown
        ])
        hbox_deck = HBox([vbox2,vbox1,vbox3])
        
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
        
        self.send_deck_label = Label(value="OT2 IP:")
        self.send_deck_input = Text(value="piot2")
        self.send_deck_button = Button(description="Send Deck")
        hbox_send = HBox([
            self.send_deck_label,
            self.send_deck_input,
            self.send_deck_button,
        ])
        vbox = VBox([hbox_deck,hbox_saveload,hbox_send])
        
        return vbox
    