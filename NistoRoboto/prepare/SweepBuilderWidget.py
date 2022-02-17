import numpy as np
import pandas as pd
import xarray as xr
from math import sqrt

import plotly.graph_objects as go
import plotly.express as px

import ipywidgets
from ipywidgets import Layout,Label,Button,Checkbox,VBox,HBox,Text
import pickle

import NistoRoboto.prepare 
from NistoRoboto.shared.units import units

class SweepBuilderWidget:
    def __init__(self,stock_dict):
        self.data_model = SweepBuilderWidget_Model(stock_dict)
        self.data_view = SweepBuilderWidget_View()
       
    def calc_sweep_cb(self,click):
        sweep = self.data_model.calc_sweep()
        return sweep
    def calc_sweep(self):
        spec = {}
        components = []
        vary = []
        lo = []
        hi = []
        num = []
        unit_list = []
        for component_name,items in self.data_view.sweep_spec.items():
            if component_name == 'total':
                continue
            components.append(component_name)
            if ('vary' in items) and (items['vary'].value==True):
                unit = items['units'].value
                if '%' in unit:
                    unit = units('')
                else:
                    unit = units(unit)
                vary.append(component_name)
                lo.append(items['lower'].value*unit)
                hi.append(items['upper'].value*unit)
                num.append(items['steps'].value)
        result = NistoRoboto.prepare.compositionSweepFactory(
            name='SweepBuilder',
            components = components,
            vary_components = vary,
            lo=lo,
            hi=hi,
            num=num,
            progress = self.data_view.sweep_progress
        )
        return result
    def update_component_row_cb(self,event): 
        component_name = event['owner'].component_name
        if event['new']==True:
            self.data_view.sweep_spec[component_name]['amount'].layout.visibility='hidden'
            self.data_view.sweep_spec[component_name]['steps'].layout.visibility='visible'
            self.data_view.sweep_spec[component_name]['lower'].layout.visibility='visible'
            self.data_view.sweep_spec[component_name]['upper'].layout.visibility='visible'
        elif event['new']==False:
            self.data_view.sweep_spec[component_name]['amount'].layout.visibility='visible'
            self.data_view.sweep_spec[component_name]['steps'].layout.visibility='hidden'
            self.data_view.sweep_spec[component_name]['lower'].layout.visibility='hidden'
            self.data_view.sweep_spec[component_name]['upper'].layout.visibility='hidden'
        
    def start(self):
        widget = self.data_view.start(self.data_model.component_names)
        
        self.data_view.sweep_button.on_click(self.calc_sweep_cb)
        for component_name,items in self.data_view.sweep_spec.items():
            if 'vary' in items:
                #this is gross but my normal lambda wrapping doesn't work because Python is Python
                items['vary'].component_name = component_name
                items['vary'].observe(self.update_component_row_cb,names=['value'])
            
        return widget
    
class SweepBuilderWidget_Model:
    def __init__(self,stock_dict):
        self.stocks = stock_dict
        self.stock_names = list(stock_dict.keys())
        
        self.component_names = set()
        for stock_name,stock in stock_dict.items():
            for component_name in stock['components'].keys():
                self.component_names.add(component_name)

class SweepBuilderWidget_View:
    def __init__(self):
        self.sweep_spec = None
        
    def make_stock_grid(self,component_names):
        self.stock_grid_nrows = len(component_names)
        self.stock_grid_ncols = 7
        text_width='100px'
        layout = ipywidgets.Layout(
            #grid_template_columns='10px '+(text_width+' ')*(self.stock_grid_ncols-1),
            #grid_template_rows='20px'*self.stock_grid_nrows,
            grid_gap='0px',
        )
        stock_grid = ipywidgets.GridspecLayout( 
            n_rows=self.stock_grid_nrows+2, 
            n_columns=self.stock_grid_ncols,
            layout=layout,
        )
        
        stock_grid[0,0] = ipywidgets.Label(value='Vary',layout=Layout(width='35px'))
        stock_grid[0,1] = ipywidgets.Label(value='Component',layout=Layout(width=text_width))
        stock_grid[0,2] = ipywidgets.Label(value='Amount',layout=Layout(width=text_width))
        stock_grid[0,3] = ipywidgets.Label(value='Steps',layout=Layout(width=text_width))
        stock_grid[0,4] = ipywidgets.Label(value='Lower',layout=Layout(width=text_width))
        stock_grid[0,5] = ipywidgets.Label(value='Upper',layout=Layout(width=text_width))
        stock_grid[0,6] = ipywidgets.Label(value='Units',layout=Layout(width=text_width))
         
        i = 1
        self.sweep_spec = {}
        for component_name in component_names: 
            stock_grid[i,0] = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False)
            stock_grid[i,1] = ipywidgets.Text(value=component_name,disabled=True,layout=Layout(width=text_width))
            stock_grid[i,2] = ipywidgets.FloatText(value=0.1,layout=Layout(width=text_width))
            stock_grid[i,3] = ipywidgets.IntText(value=2,layout=Layout(width=text_width,visibility='hidden'))
            stock_grid[i,4] = ipywidgets.FloatText(value=0.0,layout=Layout(width=text_width,visibility='hidden'))
            stock_grid[i,5] = ipywidgets.FloatText(value=1.0,layout=Layout(width=text_width,visibility='hidden'))
            stock_grid[i,6] = ipywidgets.Text(value='mass%',layout=Layout(width=text_width))
            
            self.sweep_spec[component_name] = {}
            self.sweep_spec[component_name]['vary']  = stock_grid[i,0]
            self.sweep_spec[component_name]['amount'] = stock_grid[i,2]
            self.sweep_spec[component_name]['steps'] = stock_grid[i,3]
            self.sweep_spec[component_name]['lower'] = stock_grid[i,4]
            self.sweep_spec[component_name]['upper'] = stock_grid[i,5]
            self.sweep_spec[component_name]['units'] = stock_grid[i,6]
            self.sweep_spec[component_name]['row'] = i
            i+=1
            
        stock_grid[i,1] = ipywidgets.Text(value='Total',disabled=True,layout=Layout(width=text_width))
        stock_grid[i,2] = ipywidgets.FloatText(value=0.0,layout=Layout(width=text_width))
        stock_grid[i,6] = ipywidgets.Text(value='mass%',layout=Layout(width=text_width))
        self.sweep_spec['total'] = {}
        self.sweep_spec['total']['amount'] = stock_grid[i,2]
        self.sweep_spec['total']['units'] = stock_grid[i,6]
        self.sweep_spec['total']['row'] = i
        i+=1
           
        
        self.sweep_button = ipywidgets.Button(description="Calculate Sweep")
        self.sweep_progress = ipywidgets.IntProgress(min=0,max=100,value=100)
        vbox = VBox([stock_grid,self.sweep_button,self.sweep_progress])
        return vbox
    
    def make_ternary_plot(self,component_names):  
        self.ternary = go.FigureWidget([ 
            go.Scatterternary( 
                a = [], 
                b = [], 
                c = [], 
                mode = 'markers', 
                opacity=1.0,
                showlegend=False,
            ) ],
            layout=dict(width=600),
        )
        label_A = Label('Component A')
        self.ternary_component_A_select = ipywidgets.Dropdown(
            options=component_names,
            value=component_names[0],
            layout=Layout(width='100px'),
        )
        label_B = Label('Component B')
        self.ternary_component_B_select = ipywidgets.Dropdown(
            options=component_names,
            value=component_names[1],
            layout=Layout(width='100px'),
        )
        label_C = Label('Component C')
        self.ternary_component_C_select = ipywidgets.Dropdown(
            options=component_names,
            value=component_names[2],
            layout=Layout(width='100px'),
        )
        
        self.ternary_plot_button = Button(description='Update Plot')
        
        hbox = HBox([
            VBox([label_A,self.ternary_component_A_select]),
            VBox([label_B,self.ternary_component_B_select]),
            VBox([label_C,self.ternary_component_C_select]),
        ])
        
        return VBox([hbox, self.ternary_plot_button ,self.ternary])
    
    def make_binary_plot(self,component_names):  
        self.binary = go.FigureWidget([ 
            go.Scatter( 
                x = [], 
                y = [], 
                mode = 'markers', 
                opacity=1.0,
                showlegend=False,
            ) ],
            layout=dict(width=600),
        )
        label_A = Label('Component A')
        self.binary_component_A_select = ipywidgets.Dropdown(
            options=component_names,
            value=component_names[0],
            layout=Layout(width='100px'),
        )
        label_B = Label('Component B')
        self.binary_component_B_select = ipywidgets.Dropdown(
            options=component_names,
            value=component_names[1],
            layout=Layout(width='100px'),
        )
        self.binary_plot_button = Button(description='Update Plot')
        
        hbox = HBox([
            VBox([label_A,self.binary_component_A_select]),
            VBox([label_B,self.binary_component_B_select]),
        ])
        return VBox([hbox,self.binary_plot_button,self.binary])
    
    def start(self,component_names):
        component_names =list(component_names)
        
        stock_grid = self.make_stock_grid(component_names)
        ternary = self.make_ternary_plot(component_names)
        binary = self.make_binary_plot(component_names)
        
        
        self.tabs = ipywidgets.Tab()
        self.tabs.children = [stock_grid,ternary,binary]
        self.tabs.set_title(0,'Calculate')
        self.tabs.set_title(1,'Plot Ternary')
        self.tabs.set_title(2,'Plot Binary')
        
        return self.tabs
        
        
