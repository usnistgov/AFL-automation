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

class SweepBuilderWidget:
    def __init__(self,deck):
        self.data_model = SweepBuilderWidget_Model(deck)
        self.data_view = SweepBuilderWidget_View()
    
    def plot_binary_cb(self,click):
        if self.data_model.sample_series is None:
            return
        
        component_A = self.data_view.binary_component_A_select.value
        component_B = self.data_view.binary_component_B_select.value
        x = []
        y = []
        x_validated = []
        y_validated = []
        for sample,validated in self.data_model.sample_series:
            mass_A = sample.target_check[component_A].mass.to('mg')
            mass_B = sample.target_check[component_B].mass.to('mg')
            if (abs(mass_A.magnitude)>1e4) or (abs(mass_B.magnitude)>1e4):
                #need to weed out erroneous calculations...
                continue
            x.append(mass_A.magnitude)
            y.append(mass_B.magnitude)
            if validated:
                x_validated.append(mass_A.magnitude)
                y_validated.append(mass_B.magnitude)
            
        self.data_view.binary.data[0].update(x=x,y=y)
        self.data_view.binary.layout.update({
            'xaxis.title':component_A + f' ({mass_A.units})',
            'yaxis.title':component_B + f' ({mass_B.units})'
        })
        if x_validated:
            self.data_view.binary.data[1].update(x=x_validated,y=y_validated)
        
    def plot_ternary_cb(self,click):
        if not self.data_model.sweep:
            return
        
        component_A = self.data_view.ternary_component_A_select.value
        component_B = self.data_view.ternary_component_B_select.value
        component_C = self.data_view.ternary_component_C_select.value
        a = []
        b = []
        c = []
        a_validated = []
        b_validated = []
        c_validated = []
        for sample,validated in self.data_model.sample_series:
            mass_A = sample.target_check[component_A].mass.to('mg')
            mass_B = sample.target_check[component_B].mass.to('mg')
            mass_C = sample.target_check[component_C].mass.to('mg')
            if (abs(mass_A.magnitude)>1e4) or (abs(mass_B.magnitude)>1e4) or (abs(mass_C.magnitude)>1e4):
                #need to weed out erroneous calculations...
                continue
            a.append(mass_A.magnitude)
            b.append(mass_B.magnitude)
            c.append(mass_C.magnitude)
            if validated:
                a_validated.append(mass_A.magnitude)
                b_validated.append(mass_B.magnitude)
                c_validated.append(mass_C.magnitude)
                
        self.data_view.ternary.data[0].update(a=a,b=b,c=c)
        self.data_view.ternary.layout.update({
            'ternary.aaxis.title':component_A,
            'ternary.baxis.title':component_B,
            'ternary.caxis.title':component_C 
        })
        if a_validated:
            self.data_view.ternary.data[1].update(a=a_validated,b=b_validated,c=c_validated)
       
    def calc_sweep_cb(self,click):
        sweep_data = self.get_sweep_data()
        self.data_view.sweep_progress_label.value = 'Calculating sweep compositions...'
        sweep = self.data_model.calc_sweep(sweep_data,self.data_view.sweep_progress)
        ntotal = len(self.data_model.sample_series.samples)
        self.data_view.sweep_progress_label.value = f'Done! Made {ntotal} samples.'
        
    def validate_sweep_cb(self,click):
        self.data_view.sweep_progress_label.value = 'Validating sweep compositions...'
        sweep = self.data_model.validate_sweep(
            self.data_view.validate_tol.value, 
            self.data_view.sweep_progress
        )
        ntotal = len(self.data_model.sample_series.samples)
        nvalidated = sum(self.data_model.sample_series.validated)
        self.data_view.sweep_progress_label.value = f'Done! Validated {nvalidated}/{ntotal} samples.'
    
    def get_sweep_data(self):
        sweep = {}
        for component_name,widgets in self.data_view.sweep_spec.items():
            sweep[component_name] = {}
            if component_name == 'total':
                sweep[component_name]['amount'] = widgets['amount'].value
                sweep[component_name]['units'] = widgets['units'].value
            else:
                for name,item in widgets.items():
                    sweep[component_name][name] = item.value
        return sweep
    
    def get_deck(self):
        return self.data_model.deck
    
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
        self.data_view.validate_button.on_click(self.validate_sweep_cb)
        for component_name,items in self.data_view.sweep_spec.items():
            if 'vary' in items:
                #this is gross but my normal lambda wrapping doesn't work because Python is Python
                items['vary'].component_name = component_name
                items['vary'].observe(self.update_component_row_cb,names=['value'])
        self.data_view.binary_plot_button.on_click(self.plot_binary_cb)
        self.data_view.ternary_plot_button.on_click(self.plot_ternary_cb)
            
        return widget
    
class SweepBuilderWidget_Model:
    def __init__(self,deck):
        self.sweep = []
        self.sample_series = None
        self.deck = deck
        self.component_names,_,_ = deck.get_components()
        #self.component_names = set()
        # for stock in deck.stocks:
        #     for component_name in stock.components.keys():
        #         self.component_names.add(component_name)
                
    def validate_sweep(self,tolerance,progress=None):
        self.deck.validate_sample_series(tolerance,progress=progress)
        return self.sample_series
        
    def calc_sweep(self,sweep_dict,progress):
        components = []
        vary = []
        lo = []
        hi = []
        num = []
        unit_list = []
        properties = None
        for component_name,items in sweep_dict.items():
            if (component_name == 'total') and (items['amount']>0):
                properties = {'volume':items['amount']*units(items['units'])}
            else:
                components.append(component_name)
                if ('vary' in items) and (items['vary']==True):
                    unit = items['units']
                    if '%' in unit:
                        unit = units('')
                    else:
                        unit = units(unit)
                    vary.append(component_name)
                    lo.append(items['lower']*unit)
                    hi.append(items['upper']*unit)
                    num.append(items['steps'])
        self.sweep = NistoRoboto.prepare.compositionSweepFactory(
            name='SweepBuilder',
            components = components,
            vary_components = vary,
            lo=lo,
            hi=hi,
            num=num,
            progress=progress,
            properties=properties,
        )
        
        self.deck.reset_targets()
        for target in self.sweep:
            self.deck.add_target(target,name='auto')
        self.sample_series = self.deck.make_sample_series(reset_sample_series=True)
        return self.sweep

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
            max_width='700px',
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
            stock_grid[i,2] = ipywidgets.FloatText(value=0.0,layout=Layout(width=text_width))
            stock_grid[i,3] = ipywidgets.IntText(value=5,layout=Layout(width=text_width,visibility='hidden'))
            stock_grid[i,4] = ipywidgets.FloatText(value=50.0,layout=Layout(width=text_width,visibility='hidden'))
            stock_grid[i,5] = ipywidgets.FloatText(value=200.0,layout=Layout(width=text_width,visibility='hidden'))
            stock_grid[i,6] = ipywidgets.Text(value='mg/ml',layout=Layout(width=text_width))
            
            self.sweep_spec[component_name] = {}
            self.sweep_spec[component_name]['vary']  = stock_grid[i,0]
            self.sweep_spec[component_name]['amount'] = stock_grid[i,2]
            self.sweep_spec[component_name]['steps'] = stock_grid[i,3]
            self.sweep_spec[component_name]['lower'] = stock_grid[i,4]
            self.sweep_spec[component_name]['upper'] = stock_grid[i,5]
            self.sweep_spec[component_name]['units'] = stock_grid[i,6]
            i+=1
            
        stock_grid[i,1] = ipywidgets.Text(value='Total',disabled=True,layout=Layout(width=text_width))
        stock_grid[i,2] = ipywidgets.FloatText(value=300.0,layout=Layout(width=text_width))
        stock_grid[i,6] = ipywidgets.Text(value='ul',layout=Layout(width=text_width))
        self.sweep_spec['total'] = {}
        self.sweep_spec['total']['amount'] = stock_grid[i,2]
        self.sweep_spec['total']['units'] = stock_grid[i,6]
        i+=1
           
        
        self.sweep_button = ipywidgets.Button(description="Calculate Sweep")
        #self.validate_sweep = ipywidgets.Checkbox(description="Validate Sweep",indent=False)
        self.validate_button = ipywidgets.Button(description="Validate Sweep")
        self.validate_tol = ipywidgets.FloatText(value=0.15,description="Tolerance")
        self.sweep_progress = ipywidgets.IntProgress(min=0,max=100,value=100)
        self.sweep_progress_label = ipywidgets.Label('')
        progress_hbox = HBox([self.sweep_progress,self.sweep_progress_label])
        button_hbox = HBox([self.sweep_button,self.validate_button,self.validate_tol])
        vbox = VBox([stock_grid,button_hbox,progress_hbox])
        return vbox
    
    def make_ternary_plot(self,component_names):  
        self.ternary = go.FigureWidget([ 
            go.Scatterternary( 
                a = [], 
                b = [], 
                c = [], 
                mode = 'markers', 
                marker={'color':'red'},
                opacity=1.0,
                showlegend=False,
            ) ,
            go.Scatterternary( 
                a = [], 
                b = [], 
                c = [], 
                mode = 'markers', 
                marker={'color':'blue'},
                opacity=1.0,
                showlegend=False,
            ) ,
        ],
            layout=dict(width=600,margin=dict(t=20,b=20,l=10,r=10)),
        )
        
        starting_components = []
        for i in range(3):
            try:
                starting_components.append(component_names[i])
            except IndexError:
                starting_components.append('')
                
        label_A = Label('Component A')
        self.ternary_component_A_select = ipywidgets.Dropdown(
            options=component_names,
            value=starting_components[0],
            layout=Layout(width='100px'),
        )
        
        label_B = Label('Component B')
        self.ternary_component_B_select = ipywidgets.Dropdown(
            options=component_names,
            value=starting_components[1],
            layout=Layout(width='100px'),
        )
        
        label_C = Label('Component C')
        self.ternary_component_C_select = ipywidgets.Dropdown(
            options=component_names,
            value=starting_components[2],
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
                marker={'color':'red'},
                opacity=1.0,
                showlegend=False,
            ),
            go.Scatter( 
                x = [], 
                y = [], 
                mode = 'markers', 
                marker={'color':'blue'},
                opacity=1.0,
                showlegend=False,
            ) 
        ],
            layout=dict(width=600,margin=dict(t=5,b=5,l=5,r=5)),
        )
        label_A = Label('Component A')
        starting_components = []
        for i in range(2):
            try:
                starting_components.append(component_names[i])
            except IndexError:
                starting_components.append('')
            
        self.binary_component_A_select = ipywidgets.Dropdown(
            options=component_names,
            value=starting_components[0],
            layout=Layout(width='100px'),
        )
        label_B = Label('Component B')
        self.binary_component_B_select = ipywidgets.Dropdown(
            options=component_names,
            value=starting_components[1],
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
        self.tabs.children = [stock_grid,binary,ternary]
        self.tabs.set_title(0,'Calculate')
        self.tabs.set_title(1,'Plot Binary')
        self.tabs.set_title(2,'Plot Ternary')
        
        return self.tabs
        
        
