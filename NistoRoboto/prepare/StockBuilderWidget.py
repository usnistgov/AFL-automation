import numpy as np
import pandas as pd
import xarray as xr
from math import sqrt

import plotly.graph_objects as go
import plotly.express as px

import ipywidgets
import pickle

import NistoRoboto.prepare 
from NistoRoboto.shared.units import units

class StockBuilderWidget:
    def __init__(self):
        self.data_model = StockBuilderWidget_Model()
        self.data_view = StockBuilderWidget_View()
        
    def get_stock_objects(self):
        stock_values = self.get_stock_values()
        stock_objects = self.data_model.to_stock_objects(stock_values)
        return stock_objects
    def get_stock_values(self):
        self.data_view.progress.value = 0
        progress_steps = len(self.data_view.stocks)
        stock_values = {}
        stocks = self.data_view.stocks
        for i,(stock_name,stock) in enumerate(self.data_view.stocks.items()):
            stock_values[stock_name] = {}
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
            
    def save_cb(self,click,pkl=True):
        stock_values = self.get_stock_values()
        
        filename = self.data_view.saveload_name.value
        if pkl:
            with open(filename,'wb') as f:
                pickle.dump(stock_values,f)
                
        self.data_view.progress.value = 100
    
    def load_cb(self,click):
        self.data_view.progress.value = 0
        filename = self.data_view.saveload_name.value
        with open(filename,'rb') as f: 
            save_dict = pickle.load(f)
        stocks = self.data_view.stocks
        progress_steps = len(save_dict)
        
        for i,(stock_name,stock) in enumerate(save_dict.items()):
            components = list(stock['components'].keys())
            self.data_view.make_stock_tab(stock_name,components)
            stocks[stock_name]['total']['value'].value = stock['total']['value']
            stocks[stock_name]['total']['units'].value = stock['total']['units']
            stocks[stock_name]['remove_button'].on_click(self.remove_stock_cb)
            stocks[stock_name]['mg_button'].on_click(lambda X:self.set_units_cb(X,'mg'))
            stocks[stock_name]['ul_button'].on_click(lambda X:self.set_units_cb(X,'ul'))
            stocks[stock_name]['mass%_button'].on_click(lambda X:self.set_units_cb(X,'mass%'))
            stocks[stock_name]['vol%_button'].on_click(lambda X:self.set_units_cb(X,'vol%'))
            
            for name,component in stock['components'].items():
                stocks[stock_name]['components'][name]['value'].value = component['value']
                stocks[stock_name]['components'][name]['units'].value = component['units']
            self.data_view.progress.value = ((i+1)/progress_steps)*100
        self.data_view.progress.value = 100
                
    def make_stock_cb(self,click):
        self.data_view.progress.value = 0
        stock_name = self.data_view.make_stock_name.value
        components = self.data_view.make_stock_components.value.split(',')
        self.data_view.make_stock_tab(stock_name,components)
        self.data_view.stocks[stock_name]['remove_button'].on_click(self.remove_stock_cb)
        self.data_view.stocks[stock_name]['mg_button'].on_click(lambda X:self.set_units_cb(X,'mg'))
        self.data_view.stocks[stock_name]['ul_button'].on_click(lambda X:self.set_units_cb(X,'ul'))
        self.data_view.stocks[stock_name]['mass%_button'].on_click(lambda X:self.set_units_cb(X,'mass%'))
        self.data_view.stocks[stock_name]['vol%_button'].on_click(lambda X:self.set_units_cb(X,'vol%'))
        self.data_view.progress.value = 100
        
    def remove_stock_cb(self,click):
        children = list(self.data_view.tabs.children)
        titles = []
        for i in range(len(self.data_view.tabs.children)):
            titles.append(self.data_view.tabs.get_title(i))
        
        del children[self.data_view.tabs.selected_index]
        del titles[self.data_view.tabs.selected_index]
        
        self.data_view.tabs.children = children
        for i,title in enumerate(titles):
            self.data_view.tabs.set_title(i,title)
    
    def set_units_cb(self,click,units):
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
        
        return widget


class StockBuilderWidget_Model:
    def to_stock_objects(self,all_stocks_dict):
        afl_stocks = {}
        for stock_name,stock in all_stocks_dict.items():
            components = list(stock['components'].keys())
            afl_stocks[stock_name] = NistoRoboto.prepare.Solution(stock_name,components)
            
            mass_fraction = {}
            volume_fraction = {}
            for component_name,component in stock['components'].items():
                value = component['value']
                unit_str = component['units']
                if (not value) or (not unit_str):
                    pass#empty cell, don't specify
                elif unit_str.lower() in ['mg','ug']:
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
        return afl_stocks

class StockBuilderWidget_View:
    def __init__(self):
        self.stocks = {}
        
    def make_stock_tab(self,stock_name,components):
        n_components = len(components)
        self.stocks[stock_name] = {}
        
        gs = ipywidgets.GridspecLayout(n_components+5,3)
        
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
        
            
        self.tabs.children = list(self.tabs.children) + [gs]
        self.tabs.set_title(len(self.tabs.children)-1,stock_name)
        
        
    def start(self):
        # self.label_layout = ipywidgets.Layout()
        make_stock_name_label = ipywidgets.Label(value="Stock Name")
        self.make_stock_name = ipywidgets.Text(value='Stock1')
        make_stock_components_label = ipywidgets.Label(value="Components")
        self.make_stock_components = ipywidgets.Text(value='F127,hexanes,water')
        self.make_stock_button = ipywidgets.Button(description='Create')
        self.save_stock_button = ipywidgets.Button(description='Save')
        self.load_stock_button = ipywidgets.Button(description='Load')
        saveload_name_label = ipywidgets.Label(value='Path')
        self.saveload_name = ipywidgets.Text(value='./expt.pkl')
        
        gs1 = ipywidgets.GridspecLayout(3,2)
        gs1[0,0] = make_stock_name_label
        gs1[0,1] = self.make_stock_name
        gs1[1,0] = make_stock_components_label
        gs1[1,1] = self.make_stock_components
        gs1[2,0] = self.make_stock_button
        
        gs2 = ipywidgets.GridspecLayout(2,2)
        gs2[0,0] = saveload_name_label
        gs2[0,1] = self.saveload_name
        gs2[1,0] = self.save_stock_button
        gs2[1,1] = self.load_stock_button
        
        self.make_stock_accordion = ipywidgets.Accordion([gs1,gs2])
        self.make_stock_accordion.set_title(0,'Create')
        self.make_stock_accordion.set_title(1,'Load')
        
        
        self.progress = ipywidgets.IntProgress(min=0,max=100,value=100)
        self.outputs = ipywidgets.Output()
        vbox = ipywidgets.VBox([self.make_stock_accordion,self.progress,self.outputs])
        
        self.tabs = ipywidgets.Tab()
        self.tabs.children = [vbox]
        self.tabs.set_title(0,'Setup')
        return self.tabs
        