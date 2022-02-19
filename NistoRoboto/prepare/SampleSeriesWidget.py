import numpy as np
import pandas as pd
from math import sqrt

import plotly.graph_objects as go
import plotly.express as px

import ipywidgets
from ipywidgets import Layout,Label,Button,Checkbox,VBox,HBox,Text
import pickle

import NistoRoboto.prepare 
from NistoRoboto.shared.units import units

class SampleSeriesWidget:
    def __init__(self,deck):
        self.data_model = SampleSeriesWidget_Model(deck)
        self.data_view = SampleSeriesWidget_View()
        
    def start(self):
        components = self.data_model.components
        nsamples = self.data_model.nsamples
        widget = self.data_view.start(components,nsamples)
        return widget
    
    
class SampleSeriesWidget_Model:
    def __init__(self,deck):
        self.deck = deck
        self.sample_series = deck.sample_series
        self.components,_,_ = deck.get_components()
        self.nsamples = len(deck.sample_series.samples)
    
class SampleSeriesWidget_View:
    def make_component_grid(self,components,nsamples):
        self.component_grid_nrows = len(components)
        self.component_grid_ncols = 4
        text_width='100px'
        layout = ipywidgets.Layout(
            #grid_template_columns='10px '+(text_width+' ')*(self.component_grid_ncols-1),
            #grid_template_rows='20px'*self.component_grid_nrows,
            grid_gap='0px',
            max_width='400px',
        )
        component_grid = ipywidgets.GridspecLayout( 
            n_rows=self.component_grid_nrows+1, 
            n_columns=self.component_grid_ncols,
            layout=layout,
        )
        
        component_grid[0,0] = ipywidgets.Label(value='Vary',layout=Layout(width='35px'))
        component_grid[0,1] = ipywidgets.Label(value='Component',layout=Layout(width=text_width))
        component_grid[0,2] = ipywidgets.Label(value='StringSpec',layout=Layout(width=text_width))
        component_grid[0,3] = ipywidgets.Label(value='units',layout=Layout(width=text_width))
         
        i = 1
        self.label_spec = {}
        for component in components:
            component_grid[i,0] = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False)
            component_grid[i,1] = ipywidgets.Text(value=component,disabled=True,layout=Layout(width=text_width))
            component_grid[i,2] = ipywidgets.Text(value='{:4.3f}',layout=Layout(width=text_width))
            component_grid[i,3] = ipywidgets.Text(value='mg/ml',layout=Layout(width=text_width))
            
            self.label_spec[component] = {}
            self.label_spec[component]['vary']  = component_grid[i,0]
            self.label_spec[component]['string_spec'] = component_grid[i,2]
            self.label_spec[component]['units'] = component_grid[i,3]
            i+=1
        
        self.sample_index = ipywidgets.BoundedIntText(min=0,max=nsamples-1,value=0)
        sample_label_label = ipywidgets.Label(value='Example Label:')
        self.sample_label = ipywidgets.Label(value='')
        label_hbox = HBox([self.sample_index,sample_label_label,self.sample_label])
        vbox = VBox([component_grid,label_hbox])
        return vbox
    
    def start(self,components,nsamples):
        component_grid = self.make_component_grid(components,nsamples)
        return component_grid
    
