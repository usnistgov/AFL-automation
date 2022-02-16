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
        pass
        
     
        
    def start(self):
        widget = self.data_view.start(self.data_model.component_names)
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
    def make_stock_grid2(self,stock_names):
        text_layout = ipywidgets.Layout(width='200px')
        #gs = ipywidgets.GridspecLayout(N+2,5)
        self.stock_grid_nrows = len(stock_names)
        self.stock_grid_ncols = 5
        
        self.stock_grid = np.empty((self.stock_grid_nrows+2,self.stock_grid_ncols),dtype=np.object_)
        self.stock_grid[:,:] = None
        self.stock_grid[0,0] = Label(value='Component',layout=text_layout)
        self.stock_grid[0,1] = Label(value='Vary?',layout=text_layout)
        self.stock_grid[0,2] = Label(value='Lower',layout=text_layout)
        self.stock_grid[0,3] = Label(value='Upper',layout=text_layout)
        self.stock_grid[0,4] = Label(value='Units',layout=text_layout)
         
        i = 1
        for stock in stock_names: 
            self.stock_grid[i,0] = Text(value=stock,disabled=True,layout=text_layout)
            self.stock_grid[i,1] = Checkbox(layout=text_layout)
            self.stock_grid[i,2] = Text(layout=text_layout)
            self.stock_grid[i,3] = Text(layout=text_layout)
            self.stock_grid[i,4] = Text(layout=text_layout)
            i+=1
        
        hbox = []
        for j in range(self.stock_grid_ncols):
            vbox = []
            for i in range(self.stock_grid_nrows+1):
                vbox.append(self.stock_grid[i,j])
            hbox.append(ipywidgets.VBox(vbox))
        hbox = ipywidgets.HBox(hbox)
            
        self.stock_button = Button(description="Calculate Sweep")
        self.stock_progress = ipywidgets.IntProgress(min=0,max=100,value=100)
        self.stock_grid[i,0] = self.stock_button
        self.stock_grid[i,1] = self.stock_progress
        vbox = ipywidgets.VBox([hbox,self.stock_button,self.stock_progress])
        return vbox
    def make_stock_grid(self,component_names):
        self.stock_grid_nrows = len(component_names)
        self.stock_grid_ncols = 6
        text_width='100px'
        layout = ipywidgets.Layout(
            #grid_template_columns='10px '+(text_width+' ')*(self.stock_grid_ncols-1),
            #grid_template_rows='20px'*self.stock_grid_nrows,
            grid_gap='0px',
        )
        self.stock_grid = ipywidgets.GridspecLayout( 
            n_rows=self.stock_grid_nrows+1, 
            n_columns=self.stock_grid_ncols,
            layout=layout,
        )
        
        self.stock_grid[0,0] = ipywidgets.Label(value='Vary',layout=Layout(width='35px'))
        self.stock_grid[0,1] = ipywidgets.Label(value='Component',layout=Layout(width=text_width))
        self.stock_grid[0,2] = ipywidgets.Label(value='Steps',layout=Layout(width=text_width))
        self.stock_grid[0,3] = ipywidgets.Label(value='Lower',layout=Layout(width=text_width))
        self.stock_grid[0,4] = ipywidgets.Label(value='Upper',layout=Layout(width=text_width))
        self.stock_grid[0,5] = ipywidgets.Label(value='Units',layout=Layout(width=text_width))
         
        i = 1
        for component_name in component_names: 
            self.stock_grid[i,0] = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False)
            self.stock_grid[i,1] = ipywidgets.Text(value=component_name,disabled=True,layout=Layout(width=text_width))
            self.stock_grid[i,2] = ipywidgets.IntText(value=2,layout=Layout(width=text_width))
            self.stock_grid[i,3] = ipywidgets.FloatText(value=0.0,layout=Layout(width=text_width))
            self.stock_grid[i,4] = ipywidgets.FloatText(value=1.0,layout=Layout(width=text_width))
            self.stock_grid[i,5] = ipywidgets.Text(value='mass%',layout=Layout(width=text_width))
            i+=1
        
        self.stock_button = ipywidgets.Button(description="Calculate Sweep")
        self.stock_progress = ipywidgets.IntProgress(min=0,max=100,value=100)
        vbox = VBox([self.stock_grid,self.stock_button,self.stock_progress])
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
        
        self.stock_grid = self.make_stock_grid(component_names)
        ternary = self.make_ternary_plot(component_names)
        binary = self.make_binary_plot(component_names)
        
        
        self.tabs = ipywidgets.Tab()
        self.tabs.children = [self.stock_grid,ternary,binary]
        self.tabs.set_title(0,'Calculate')
        self.tabs.set_title(1,'Plot Ternary')
        self.tabs.set_title(2,'Plot Binary')
        
        return self.tabs
        
        
