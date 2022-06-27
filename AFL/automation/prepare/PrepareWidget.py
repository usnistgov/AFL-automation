import numpy as np
import pandas as pd
from math import sqrt

import plotly.graph_objects as go
import plotly.express as px

import ipywidgets
from ipywidgets import Dropdown,Layout,Label,Button,Checkbox,VBox,HBox,Text
import pickle

import AFL.automation.prepare 
from AFL.automation.shared.units import units

from AFL.automation.prepare.StockBuilderWidget import StockBuilderWidget
from AFL.automation.prepare.SweepBuilderWidget import SweepBuilderWidget
from AFL.automation.prepare.DeckBuilderWidget import DeckBuilderWidget
from AFL.automation.prepare.SampleSeriesWidget import SampleSeriesWidget


class PrepareWidget:
    def __init__(self):
        self.data_model    = PrepareWidget_Model()
        self.data_view     = PrepareWidget_View()
        self.deck_builder  = DeckBuilderWidget()
        self.stock_builder = None
        self.sweep_builder = None
        self.sample_series_tool   = None
        
    def SweepBuilder_reset_cb(self,event):
        deck = self.stock_builder.add_stocks_to_deck()
        self.sweep_builder = SweepBuilderWidget(deck)
        widget = self.sweep_builder.start()
        
        self.data_view.SweepBuilder_Container.children = [
            self.data_view.reset_SweepBuilder_button,
            widget
        ]
        
    def StockBuilder_reset_cb(self,event):
        deck = self.deck_builder.build_deck_object()
        self.stock_builder = StockBuilderWidget(deck)
        widget = self.stock_builder.start()
        
        self.data_view.StockBuilder_Container.children = [
            self.data_view.reset_StockBuilder_button,
            widget
        ]
        
    def SampleSeriesTool_reset_cb(self,event):
        deck = self.sweep_builder.get_deck()
        self.sample_series_tool = SampleSeriesWidget(deck)
        widget = self.sample_series_tool.start()
        
        self.data_view.SampleSeriesTool_Container.children = [
            self.data_view.reset_SampleSeriesTool_button,
            widget
        ]
        
    def start(self):
        widget = self.data_view.start( self.deck_builder.start() )
        
        self.data_view.reset_StockBuilder_button.on_click(self.StockBuilder_reset_cb)
        self.data_view.reset_SweepBuilder_button.on_click(self.SweepBuilder_reset_cb)
        self.data_view.reset_SampleSeriesTool_button.on_click(self.SampleSeriesTool_reset_cb)
        return widget
        
    
class PrepareWidget_Model:
    pass
    
class PrepareWidget_View:
    def start(self,deck_builder_widget):
        
        self.tabs = ipywidgets.Tab()
        
        self.reset_StockBuilder_button = Button(description='Reset Tool')
        self.reset_SweepBuilder_button = Button(description='Reset Tool')
        self.reset_SampleSeriesTool_button = Button(description='Reset Tool')
        self.StockBuilder_Container = VBox([self.reset_StockBuilder_button])
        self.SweepBuilder_Container = VBox([self.reset_SweepBuilder_button])
        self.SampleSeriesTool_Container = VBox([self.reset_SampleSeriesTool_button])
        self.tabs.children = [
            deck_builder_widget,
            self.StockBuilder_Container,
            self.SweepBuilder_Container,
            self.SampleSeriesTool_Container,
        ]
        self.tabs.set_title(0,'Deck Setup')
        self.tabs.set_title(1,'Stock Setup')
        self.tabs.set_title(2,'Sweep Setup')
        self.tabs.set_title(3,'Sweep Submit')
        return self.tabs