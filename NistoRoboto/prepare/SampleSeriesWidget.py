import numpy as np
import pandas as pd
from math import sqrt

import plotly.graph_objects as go
import plotly.express as px

import ipywidgets
from ipywidgets import Layout,Label,Button,Checkbox,VBox,HBox,Text,FloatText,IntText
import pickle

import NistoRoboto.prepare 
from NistoRoboto.shared.units import units

class SampleSeriesWidget:
    def __init__(self,deck):
        self.data_model = SampleSeriesWidget_Model(deck)
        self.data_view = SampleSeriesWidget_View()
    
    def build_label(self,index):
        target = self.data_model.sample_series.samples[index].target_check
        prefix = self.data_view.label_spec['prefix']
        if prefix['include'].value and prefix['value'].value:#check for empty str
            label = prefix['value'].value+' '
        else:
            label = ''
            
        all_units = []
        for component_name,spec in self.data_view.label_spec.items():
            if component_name=='prefix':
                continue
            all_units.append(spec['units'].value)
            
            
        if all([i==all_units[0] for i in all_units]):
            postpend_units=True
        else:
            postpend_units=False
            
            
        for component_name,spec in self.data_view.label_spec.items():
            if not spec['include'].value:
                continue
            if component_name=='prefix':
                continue
            
            units = spec['units'].value
            if units.lower() in ['g','mg','ug']:
                amount = target[component_name].mass.to(units).magnitude
            elif units.lower() in ['l','ml','ul']:
                amount = target[component_name].volume.to(units).magnitude
            elif units.lower() in ['mg/ml','g/l','g/ml']:
                amount = target.concentration[component_name].to(units).magnitude
            else:
                return None
            amount_str = f'{spec["string_spec"].value}'
            label+= f'{component_name}:'+amount_str.format(amount)
            if not postpend_units:
                label += f'{units} '.replace('/','')
            else:
                label += ' '
        if postpend_units:
            label += f'{units}'.replace('/','')
        else:
            label = label[:-1]
        return label
    
    def example_label_cb(self,event):
        index = self.data_view.sample_index.value
        label = self.build_label(index)
        if label is not None:
            self.data_view.sample_label.value = label
            
    def make_all_labels_cb(self,event):
        labels = []
        only_validated = self.data_view.only_validated.value
        minlen = 1e6
        maxlen = -1e6
        for i,(sample,validated) in enumerate(self.data_model.sample_series):
            if only_validated and (not validated):
                continue
            labels.append(self.build_label(i)) 
            minlen = min(len(labels[-1]),minlen)
            maxlen = max(len(labels[-1]),maxlen)
        self.data_view.all_labels.options = labels
        self.data_view.make_label_result_text.value = f'Labeled {len(labels)} samples. | Min len: {minlen} | Max len: {maxlen}'
        
    def start(self):
        components = self.data_model.components
        nsamples = self.data_model.nsamples
        widget = self.data_view.start(components,nsamples)
        
        for component_name,spec in self.data_view.label_spec.items():
            spec['include'].observe(self.example_label_cb,names=['value'])
            if component_name=='prefix':
                spec['value'].observe(self.example_label_cb,names=['value'])
            else:
                spec['string_spec'].observe(self.example_label_cb,names=['value'])
                spec['units'].observe(self.example_label_cb,names=['value'])
        
        self.data_view.sample_index.observe(self.example_label_cb,names=['value'])
        self.example_label_cb(None)
        
        self.data_view.label_button.on_click(self.make_all_labels_cb)
        return widget
    
    
class SampleSeriesWidget_Model:
    def __init__(self,deck):
        self.deck = deck
        self.sample_series = deck.sample_series
        self.components,_,_ = deck.get_components()
        self.nsamples = len(deck.sample_series.samples)
    
class SampleSeriesWidget_View:
    def __init__(self):
        self.pipette_params = {}
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
        
        component_grid[0,0] = ipywidgets.Label(value='Include',layout=Layout(width='45px'))
        component_grid[0,1] = ipywidgets.Label(value='Component',layout=Layout(width=text_width))
        component_grid[0,2] = ipywidgets.Label(value='StringSpec',layout=Layout(width=text_width))
        component_grid[0,3] = ipywidgets.Label(value='units',layout=Layout(width=text_width))
         
        i = 1
        self.label_spec = {}
        for component in components:
            component_grid[i,0] = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False,value=True)
            component_grid[i,1] = ipywidgets.Text(value=component,disabled=True,layout=Layout(width=text_width))
            component_grid[i,2] = ipywidgets.Text(value='{:4.1f}',layout=Layout(width=text_width))
            component_grid[i,3] = ipywidgets.Text(value='mg/ml',layout=Layout(width=text_width))
            
            self.label_spec[component] = {}
            self.label_spec[component]['include']  = component_grid[i,0]
            self.label_spec[component]['string_spec'] = component_grid[i,2]
            self.label_spec[component]['units'] = component_grid[i,3]
            i+=1
        
        prefix_check = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False,value=True)
        prefix_text = ipywidgets.Text(description='Prefix:',value='')
        
        self.label_spec['prefix'] = {}
        self.label_spec['prefix']['include']  = prefix_check
        self.label_spec['prefix']['value'] = prefix_text
        
        self.sample_index = ipywidgets.BoundedIntText(min=0,max=nsamples-1,value=0,layout={'width':'50px'})
        sample_label_label = Label(value='Example Label:')
        self.sample_label = Label(value='')
        
        self.label_button = Button(description='Make All Labels')
        self.all_labels = ipywidgets.SelectMultiple(layout={'width':'400px'})
        label = Label('Only Validated')
        self.make_label_result_text = Label('')
        self.only_validated = Checkbox(indent=False,value=True)
        box = VBox([
            HBox([self.label_button,label,self.only_validated]),
            self.make_label_result_text
        ])
        
        label_hbox = HBox([self.sample_index,sample_label_label,self.sample_label])
        prefix_hbox = HBox([prefix_check,prefix_text])
        vbox = VBox([component_grid,prefix_hbox,label_hbox,box,self.all_labels])
        return vbox
    
    def make_pipette_params(self,name):
        self.pipette_params[name] = {}
        
        label = Label(value='Aspirate Rate (uL/s)')
        text = FloatText(value=150)
        hbox1 = HBox([label,text])
        self.pipette_params[name]['aspirate_rate'] = text
        
        label = Label(value='Dispense Rate (uL/s)')
        text = FloatText(value=300)
        hbox2 = HBox([label,text])
        self.pipette_params[name]['dispense_rate'] = text
        
        label = Label(value='Post Aspirate Delay (s)')
        text = FloatText(value=0)
        hbox3 = HBox([label,text])
        self.pipette_params[name]['post_aspirate_delay'] = text
        
        label = Label(value='Post Dispense Delay (s)')
        text = FloatText(value=0)
        hbox4 = HBox([label,text])
        self.pipette_params[name]['post_dispense_delay'] = text
        
        label1 = Label(value='Num. Mixes Before')
        text1 = IntText(value=0,layout={'width':'50px'})
        label2 = Label(value='Mix Volume')
        text2 = IntText(value=300.0)
        hbox5 = HBox([label1,text1,label2,text2])
        self.pipette_params[name]['mix_before_num'] = text1
        self.pipette_params[name]['mix_before_vol'] = text2
        
        label1 = Label(value='Num. Mixes After')
        text1 = IntText(value=0,layout={'width':'50px'})
        label2 = Label(value='Mix Volume')
        text2 = IntText(value=300.0)
        hbox6 = HBox([label1,text1,label2,text2])
        self.pipette_params[name]['mix_after_num'] = text1
        self.pipette_params[name]['mix_after_vol'] = text2
        
        vbox = VBox([
            hbox1,
            hbox2,
            hbox3,
            hbox4,
            hbox5,
            hbox6
        ])
        return vbox
            
    def start(self,components,nsamples):
        component_grid = self.make_component_grid(components,nsamples)
        
        pipette_prepare_params = self.make_pipette_params('prepare')
        pipette_load_params = self.make_pipette_params('load')
        
        
        self.tabs = ipywidgets.Tab([component_grid,pipette_prepare_params,pipette_load_params])
        self.tabs.set_title(0,'Label')
        self.tabs.set_title(1,'Prepare Params')
        self.tabs.set_title(2,'Load Params')
        
        self.ip = Text(value='localhost:5000')
        self.submit = Button(description='Submit')
        hbox = HBox([self.ip,self.submit])
        vbox = VBox([self.tabs,hbox])
        return vbox
    
