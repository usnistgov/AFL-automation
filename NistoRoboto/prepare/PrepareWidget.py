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

from NistoRoboto.prepare.StockBuilderWidget import StockBuilderWidget
from NistoRoboto.prepare.SweepBuilderWidget import SweepBuilderWidget
from NistoRoboto.prepare.DeckBuilderWidget import DeckBuilderWidget


class PrepareWidget:
    def __init__(self):
        self.data_model = PrepareWidget_Model()
        self.data_view = PrepareWidget_View()
        self.deck_builder = DeckBuilderWidget()
        self.stock_builder = StockBuilderWidget()
        self.sweep_builder = None
    def sweep_reset_cb(self,event):
        stock_dict = self.stock_builder.get_stock_values()
        if not stock_dict:
            raise ValueError("Cannot build sweep with stocks specified!")
        self.sweep_builder = SweepBuilderWidget(stock_dict)
        widget = self.sweep_builder.start()
        
        self.data_view.sweep_holder.children = [
            self.data_view.reset_sweep_button,
            widget
        ]
    def start(self):
        widget = self.data_view.start(
            self.deck_builder.start(),
            self.stock_builder.start(),
        )
        
        self.data_view.reset_sweep_button.on_click(self.sweep_reset_cb)
        return widget
        
    
class PrepareWidget_Model:
    pass
    
class PrepareWidget_View:
    def start(self,deck_builder_widget,stock_builder_widget):
        
        self.tabs = ipywidgets.Tab()
        
        self.reset_sweep_button = Button(description='Reset Sweep')
        self.sweep_holder = VBox([self.reset_sweep_button])
        self.tabs.children = [deck_builder_widget,stock_builder_widget,self.sweep_holder]
        self.tabs.set_title(0,'Deck Setup')
        self.tabs.set_title(1,'Stock Setup')
        self.tabs.set_title(2,'Sweep Setup')
        return self.tabs