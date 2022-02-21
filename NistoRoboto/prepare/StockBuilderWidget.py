import numpy as np
import pandas as pd
from math import sqrt
import re

import plotly.graph_objects as go
import plotly.express as px

import ipywidgets
import pickle

import NistoRoboto.prepare 
from NistoRoboto.shared.units import units

class StockBuilderWidget:
    def __init__(self,deck):
        self.data_model = StockBuilderWidget_Model(deck)
        self.data_view = StockBuilderWidget_View()
        
    def analyze_stocks_cb(self,event):
        stocks,locs = self.get_stock_objects()
        text = ''
            
        components = set()
        for stock_name,stock in stocks.items():
            for component in stock.components.keys():
                components.add(component)
            
        text+='{:25s} | {:26s} | {}\n'.format('component','stock_name','concentration')
        text+='{:25s} | {:26s} | {}\n'.format('-'*25,'-'*25,'-'*25)
        for component in components:
            for stock_name,stock in stocks.items():
                if component in stock.components:
                    text+=f'{component:25s} |  {stock_name:25s} | {stock.concentration[component].to("mg/ml")}\n'
            text+='-'*100 + '\n'
        self.data_view.analyze_stocks_text.value = text
            
    def get_stock_objects(self):
        stock_values = self.get_stock_values()
        stock_objects = self.data_model.to_stock_objects(stock_values)
        return stock_objects
    
    def add_stocks_to_deck(self):
        stock_values = self.get_stock_values()
        stock_objects = self.data_model.add_stocks_to_deck(stock_values)
        return self.data_model.deck
    
    def get_stock_values(self):
        self.data_view.progress.value = 0
        progress_steps = len(self.data_view.stocks)
        stock_values = {}
        stocks = self.data_view.stocks
        for i,(stock_name,stock) in enumerate(self.data_view.stocks.items()):
            stock_values[stock_name] = {}
            stock_values[stock_name]['location'] = {
                'value':stock['location']['value'].value
            }
            stock_values[stock_name]['total'] = {
                'value':stock['total']['value'].value,
                'units':stock['total']['units'].value
            }
            stock_values[stock_name]['components'] = {}
            for name,component in stock['components'].items():
                stock_values[stock_name]['components'][name] = {
                    'value':component['value'].value,
                    'units':component['units'].value
                }
            self.data_view.progress.value = ((i+1)/progress_steps)*100
        self.data_view.progress.value = 100
        return stock_values
            
    def save_cb(self,event,pkl=True):
        stock_values = self.get_stock_values()
        
        filename = self.data_view.saveload_name.value
        if pkl:
            with open(filename,'wb') as f:
                pickle.dump(stock_values,f)
                
        self.data_view.progress.value = 100
    
    def load_cb(self,event):
        self.data_view.progress.value = 0
        filename = self.data_view.saveload_name.value
        with open(filename,'rb') as f: 
            save_dict = pickle.load(f)
        stocks = self.data_view.stocks
        progress_steps = len(save_dict)
        
        for i,(stock_name,stock) in enumerate(save_dict.items()):
            components = list(stock['components'].keys())
            self.data_view.make_stock_tab(stock_name,components)
            stocks[stock_name]['location']['value'].value = stock['location']['value']
            stocks[stock_name]['total']['value'].value    = stock['total']['value']
            stocks[stock_name]['total']['units'].value    = stock['total']['units']
            stocks[stock_name]['remove_button'].on_click(self.remove_stock_cb)
            stocks[stock_name]['mg_button'].on_click(lambda X:self.set_units_cb(X,'mg'))
            stocks[stock_name]['ul_button'].on_click(lambda X:self.set_units_cb(X,'ul'))
            stocks[stock_name]['mass%_button'].on_click(lambda X:self.set_units_cb(X,'mass%'))
            stocks[stock_name]['vol%_button'].on_click(lambda X:self.set_units_cb(X,'vol%'))
            stocks[stock_name]['location']['value'].observe(self.update_location_check_cb,names=['value'])
            
            self.data_view.tabs.selected_index= (len(self.data_view.tabs.children)-1)
            self.update_location_check_cb(None)#trigger location_check
            
            for name,component in stock['components'].items():
                stocks[stock_name]['components'][name]['value'].value = component['value']
                stocks[stock_name]['components'][name]['units'].value = component['units']
            self.data_view.progress.value = ((i+1)/progress_steps)*100
        self.data_view.progress.value = 100
                
    def update_location_check_cb(self,event):
        index =  self.data_view.tabs.selected_index
        stock_name = self.data_view.tabs.get_title(index)
        location = self.data_view.stocks[stock_name]['location']['value'].value
        
        split = re.split('[a-zA-z]',location)
        if not len(split)==2:
            return
        
        try:
            loc = int(split[0])
        except ValueError:
            return
            
        deckware = self.data_model.deck.all_deckware[loc]
        self.data_view.stocks[stock_name]['location']['check_text'].value = f'Slot contains: {deckware}'
        
    def make_stock_cb(self,event):
        self.data_view.progress.value = 0
        stock_name = self.data_view.make_stock_name.value
        components = self.data_view.make_stock_components.value.split(',')
        self.data_view.make_stock_tab(stock_name,components)
        self.data_view.stocks[stock_name]['remove_button'].on_click(self.remove_stock_cb)
        self.data_view.stocks[stock_name]['mg_button'].on_click(lambda X:self.set_units_cb(X,'mg'))
        self.data_view.stocks[stock_name]['ul_button'].on_click(lambda X:self.set_units_cb(X,'ul'))
        self.data_view.stocks[stock_name]['mass%_button'].on_click(lambda X:self.set_units_cb(X,'mass%'))
        self.data_view.stocks[stock_name]['vol%_button'].on_click(lambda X:self.set_units_cb(X,'vol%'))
        self.data_view.stocks[stock_name]['location']['value'].observe(self.update_location_check_cb,names=['value'])
        self.data_view.progress.value = 100
        
    def remove_stock_cb(self,event):
        children = list(self.data_view.tabs.children)
        titles = []
        for i in range(len(self.data_view.tabs.children)):
            titles.append(self.data_view.tabs.get_title(i))
        
        del children[self.data_view.tabs.selected_index]
        stock_name = titles[self.data_view.tabs.selected_index]
        del self.data_view.stocks[stock_name]
        del titles[self.data_view.tabs.selected_index]
        
        self.data_view.tabs.children = children
        for i,title in enumerate(titles):
            self.data_view.tabs.set_title(i,title)
    
    def set_units_cb(self,event,units):
        index =  self.data_view.tabs.selected_index
        stock_name = self.data_view.tabs.get_title(index)
        self.data_view.stocks[stock_name]['total']['units'].value =  units
        for name,component in self.data_view.stocks[stock_name]['components'].items():
            component['units'].value = units
        
    def start(self):
        widget = self.data_view.start()
        self.data_view.save_stock_button.on_click(self.save_cb)
        self.data_view.load_stock_button.on_click(self.load_cb)
        self.data_view.make_stock_button.on_click(self.make_stock_cb)
        self.data_view.analyze_stocks_button.on_click(self.analyze_stocks_cb)
        
        return widget


class StockBuilderWidget_Model:
    def __init__(self,deck):
        self.deck = deck
        
    def add_stocks_to_deck(self,all_stocks_dict):
        stocks,locs = self.to_stock_objects(all_stocks_dict)
        self.deck.reset_stocks()
        for stock_name,stock_obj in stocks.items():
            self.deck.add_stock(stock_obj,locs[stock_name])
            
    def to_stock_objects(self,all_stocks_dict):
        afl_stocks = {}
        afl_stock_locs = {}
        for stock_name,stock in all_stocks_dict.items():
            components = list(stock['components'].keys())
            afl_stocks[stock_name] = NistoRoboto.prepare.Solution(stock_name,components)
            afl_stock_locs[stock_name] = stock['location']['value']
            
            mass_fraction = {}
            volume_fraction = {}
            for component_name,component in stock['components'].items():
                value = component['value']
                unit_str = component['units']
                if (not value) or (not unit_str):
                    pass#empty cell, don't specify
                elif unit_str.lower() in ['mg','ug','g']:
                    afl_stocks[stock_name][component_name].mass = float(value)*units(unit_str)
                elif unit_str.lower() in ['ul','ml','l']:
                    afl_stocks[stock_name][component_name].volume = float(value)*units(unit_str)
                elif unit_str.lower() in ['m%','mass%']:
                    mass_fraction[component_name] = float(value)
                elif unit_str.lower() in ['v%','vol%']:
                    volume_fraction[component_name] = float(value)
                else:
                    raise ValueError(f'Units not recogized: {unit_str}')
                
            if mass_fraction:
                afl_stocks[stock_name].mass_fraction = mass_fraction
                
            if volume_fraction:
                afl_stocks[stock_name].volume_fraction = volume_fraction
                
            value = stock['total']['value']
            unit_str = stock['total']['units']
            if (not value) or (not unit_str):
                pass#empty cell, don't specify
            elif unit_str.lower() in ['mg','ug']:
                afl_stocks[stock_name].mass = float(value)*units(unit_str)
            elif unit_str.lower() in ['ul','ml','l']:
                afl_stocks[stock_name].volume = float(value)*units(unit_str)
            else:
                raise ValueError(f'Units not recogized: {unit_str}')
        return afl_stocks,afl_stock_locs

class StockBuilderWidget_View:
    def __init__(self):
        self.stocks = {}
        
    def make_stock_tab(self,stock_name,components):
        n_components = len(components)
        self.stocks[stock_name] = {}
        
        gs = ipywidgets.GridspecLayout(n_components+6,3)
        
        i=0
        gs[i,0] = ipywidgets.Button(description="Remove Stock")
        self.stocks[stock_name]['remove_button'] = gs[i,0]
        i+=1
        
        gs[i,1] = ipywidgets.Label(value='Amount')
        gs[i,2] = ipywidgets.Label(value='Units')
        i+=1
            
        gs[i,0] = ipywidgets.Label(value="Total")
        gs[i,1] = ipywidgets.Text()
        gs[i,2] = ipywidgets.Text(placeholder='mg')
        self.stocks[stock_name]['total'] = {'value':gs[i,1],'units':gs[i,2]}
        i+=1
        
        self.stocks[stock_name]['components'] = {}
        for name in components:
            gs[i,0] = ipywidgets.Label(value=f"{name}")
            gs[i,1] = ipywidgets.Text()
            gs[i,2] = ipywidgets.Text(placeholder=f'mg')
            self.stocks[stock_name]['components'][name] = {
                'value':gs[i,1],
                'units':gs[i,2]
            }
            i+=1
            
            
        gs2 = ipywidgets.GridspecLayout(1,2)
        gs2[0,0] = ipywidgets.Button(description="All mg")
        gs2[0,1] = ipywidgets.Button(description="All ul")
        self.stocks[stock_name]['mg_button'] = gs2[0,0]
        self.stocks[stock_name]['ul_button'] = gs2[0,1]
        gs[i,2] = gs2
        i+=1
        
        gs2 = ipywidgets.GridspecLayout(1,2)
        gs2[0,0] = ipywidgets.Button(description="All mass%")
        gs2[0,1] = ipywidgets.Button(description="All vol%")
        self.stocks[stock_name]['mass%_button'] = gs2[0,0]
        self.stocks[stock_name]['vol%_button'] = gs2[0,1]
        gs[i,2] = gs2
        i+=1
        
        gs[i,0] = ipywidgets.Label(value=f"Deck Location")
        gs[i,1] = ipywidgets.Text()
        gs[i,2] = ipywidgets.Label(value="",style={'font_style':'italic'})
        self.stocks[stock_name]['location'] = {
            'value':gs[i,1],
            'check_text':gs[i,2],
        }
        i+=1
        
            
        self.tabs.children = list(self.tabs.children) + [gs]
        self.tabs.set_title(len(self.tabs.children)-1,stock_name)
        
    def start(self):
        # self.label_layout = ipywidgets.Layout()
        make_stock_name_label = ipywidgets.Label(value="Stock Name")
        self.make_stock_name = ipywidgets.Text(value='Stock1')
        make_stock_components_label = ipywidgets.Label(value="Components")
        self.make_stock_components = ipywidgets.Text(value='F127,hexanes,water')
        #make_stock_location_label = ipywidgets.Label(value="Deck Location")
        #self.make_stock_location = ipywidgets.Text(value='1A1')
        self.make_stock_button = ipywidgets.Button(description='Create')
        self.save_stock_button = ipywidgets.Button(description='Save')
        self.load_stock_button = ipywidgets.Button(description='Load')
        saveload_name_label = ipywidgets.Label(value='Path')
        self.saveload_name = ipywidgets.Text(value='./expt.pkl')
        
        gs1 = ipywidgets.GridspecLayout(4,2)
        gs1[0,0] = make_stock_name_label
        gs1[0,1] = self.make_stock_name
        gs1[1,0] = make_stock_components_label
        gs1[1,1] = self.make_stock_components
        # gs1[2,0] = make_stock_location_label
        # gs1[2,1] = self.make_stock_location
        gs1[2,0] = self.make_stock_button
        
        gs2 = ipywidgets.GridspecLayout(2,2)
        gs2[0,0] = saveload_name_label
        gs2[0,1] = self.saveload_name
        gs2[1,0] = self.save_stock_button
        gs2[1,1] = self.load_stock_button
        
        self.make_stock_accordion = ipywidgets.Accordion([gs1,gs2])
        self.make_stock_accordion.set_title(0,'Create')
        self.make_stock_accordion.set_title(1,'Save & Load')
        
        self.progress = ipywidgets.IntProgress(min=0,max=100,value=100)
        self.outputs = ipywidgets.Output()
        vbox1 = ipywidgets.VBox([self.make_stock_accordion,self.progress,self.outputs])
        
        self.analyze_stocks_button = ipywidgets.Button(description='Analyze')
        self.analyze_stocks_text = ipywidgets.Textarea(layout=ipywidgets.Layout(width='800px',height='600px'))
        self.analyze_container = ipywidgets.VBox([self.analyze_stocks_button,self.analyze_stocks_text])
        
        self.tabs = ipywidgets.Tab()
        self.tabs.children = [vbox1,self.analyze_container]
        self.tabs.set_title(0,'Setup')
        self.tabs.set_title(1,'Analyze')
        return self.tabs
        