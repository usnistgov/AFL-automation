import numpy as np
import pandas as pd
from math import sqrt

import plotly.graph_objects as go
import plotly.express as px

import itertools
import ipywidgets
from ipywidgets import Layout,Label,Button,Checkbox,VBox,HBox,Text,FloatText,IntText
import pickle

import AFL.automation.prepare 
from AFL.automation.shared.units import units
from AFL.automation.APIServer.client.Client import Client


class SampleSeriesWidget:
    def __init__(self,deck):
        self.data_model = SampleSeriesWidget_Model(deck)
        self.data_view = SampleSeriesWidget_View()
        

    def apply_protocol_order_cb(self,event):
        self.apply_protocol_order()
        self.update_protocol_order_preview_cb(None)
        
    def apply_protocol_order(self):
        self.make_protocol()
        mix_order = []
        deck_map = {v:k for k,v in self.data_model.deck.stock_location.items()}
        for item in self.data_view.protocol_order.options:
            mix_order.append(self.data_model.deck.get_stock(item))
        reordered_items = self.data_model.adjust_protocol_order(mix_order)
        self.data_model.protocol_order_old = [[(j,deck_map[j.source].name) for j in i[0]] for i in reordered_items if i]
        self.data_model.protocol_order_new = [[(j,deck_map[j.source].name) for j in i[1]] for i in reordered_items if i]
        index = self.data_view.protocol_index.min = 0
        index = self.data_view.protocol_index.max = len(self.data_model.protocol_order_old)
    
    def update_protocol_order_preview_cb(self,event):
        index = self.data_view.protocol_index.value
        self.data_view.protocol_order_preview1.options = [str(i) for i in self.data_model.protocol_order_old[index]]
        self.data_view.protocol_order_preview2.options = [str(i) for i in self.data_model.protocol_order_new[index]]
        
    def make_protocol(self):
        self.data_model.deck.make_protocol(only_validated=True)
        for i,(sample,validated) in enumerate(self.data_model.deck.sample_series):
            if not validated:
                continue
            label = self.build_label(i)
            sample.name = label
            for action in sample.protocol:
                action.post_aspirate_delay = self.data_view.pipette_params['prepare']['post_aspirate_delay'].value
                action.post_dispense_delay = self.data_view.pipette_params['prepare']['post_dispense_delay'].value
                action.aspirate_rate = self.data_view.pipette_params['prepare']['aspirate_rate'].value
                action.dispense_rate = self.data_view.pipette_params['prepare']['dispense_rate'].value
                
                mix_before_num = self.data_view.pipette_params['prepare']['mix_before_num'].value
                mix_before_vol = self.data_view.pipette_params['prepare']['mix_before_vol'].value
                if mix_before_num>0:
                    action.mix_before =(mix_before_num,mix_before_vol)
                else:
                    action.mix_before = None
                    
                mix_after_num = self.data_view.pipette_params['prepare']['mix_after_num'].value
                mix_after_vol = self.data_view.pipette_params['prepare']['mix_after_vol'].value
                if mix_after_num>0:
                    action.mix_after =(mix_after_num,mix_after_vol)
                else:
                    action.mix_after = None
    def make_catch_protocol(self):
        
        catch_locs = list(self.data_model.deck.catches.keys())
        if len(catch_locs)>1:
            raise ValueError("Not set up for multiple catches: {catch_locs}")
        else:
            catch_loc = f'{catch_locs[0]}A1'
        
        params = self.data_view.pipette_params['load']
        catch_protocol = AFL.automation.prepare.PipetteAction(
            source='target',
            dest=catch_loc,
            volume = self.data_view.load_volume.value,
            post_aspirate_delay = params['post_aspirate_delay'].value,
            post_dispense_delay = params['post_dispense_delay'].value,
            aspirate_rate = params['aspirate_rate'].value,
            dispense_rate = params['dispense_rate'].value,
         )
            
        mix_before_num = params['mix_before_num'].value
        mix_before_vol = params['mix_before_vol'].value
        if mix_before_num>0:
            catch_protocol.mix_before =(mix_before_num,mix_before_vol)
            
        mix_after_num = params['mix_after_num'].value
        mix_after_vol = params['mix_after_vol'].value
        if mix_after_num>0:
            catch_protocol.mix_after =(mix_after_num,mix_after_vol)
        return catch_protocol

    
    def submit_cb(self,event):

        self.apply_protocol_order()#will also make protocol and apply setpoints
        if self.data_view.shuffle_jobs.value:
            self.data_model.deck.sample_series.shuffle()
        catch_protocol = self.make_catch_protocol()
        ip,port = self.data_view.sample_server_ip.value.split(':')
        client = Client(ip,port=port)
        client.login('WidgetGUI')
        client.debug(False)
        
        for i,(sample,validated) in enumerate(self.data_model.deck.sample_series):
            if not validated:
                continue
            
            catch_protocol.source = sample.target_loc
            
            uuid = client.enqueue(
                task_name='sample',
                name = sample.name,
                prep_protocol = sample.emit_protocol(),
                catch_protocol =[catch_protocol.emit_protocol()],
                volume = catch_protocol.volume/1000.0,
                exposure=self.data_view.exposure_time.value,
                interactive=False
            )
            
            self.data_model.uuids.append(uuid)
        self.data_view.uuid_list.options = self.data_model.uuids
    
    def build_label(self,index):
        target = self.data_model.sample_series.samples[index].target_check
        prefix = self.data_view.label_spec['prefix']
        if prefix['include'].value and prefix['value'].value:#check for empty str
            label = prefix['value'].value+' '
        else:
            label = ''
            
        ## Determine is all units are the same
        all_units = []
        for component_name,spec in self.data_view.label_spec.items():
            if component_name=='prefix':
                continue
            elif component_name=='strip':
                continue
            elif component_name=='separator':
                continue
            all_units.append(spec['units'].value)
            
        if all([i==all_units[0] for i in all_units]):
            postpend_units=True
        else:
            postpend_units=False
            
        ## get separator
        if self.data_view.label_spec['separator']['include'].value:
            separator=self.data_view.label_spec['separator']['value'].value
        else:
            separator=':'
            
        ## build label
        for component_name,spec in self.data_view.label_spec.items():
            if not spec['include'].value:
                continue
            if component_name=='prefix':
                continue
            elif component_name=='strip':
                continue
            elif component_name=='separator':
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
            component_string = spec["component_string"].value
            label+= f'{component_string}' + separator + amount_str.format(amount)
            if not postpend_units:
                label += f'{units} '.replace('/','')
            else:
                label += ' '
                
        if postpend_units:
            label += f'{units}'.replace('/','')
        else:
            label = label[:-1]
            
        
        if self.data_view.label_spec['strip']['include'].value:
            for char in self.data_view.label_spec['strip']['value'].value:
                label = label.replace(char,'')
        return label
    
    def example_label_cb(self,event):
        index = self.data_view.sample_index.value
        label = self.build_label(index)
        if label is not None:
            self.data_view.sample_label.value = label
            
    def make_all_labels_cb(self,event):
        labels = self.make_all_labels()
        if any([l is None for l in labels]):
            self.data_view.make_label_result_text.value = f'Error!'
        else:
            minlen = len(min(labels,key=len))
            maxlen = len(max(labels,key=len))
            self.data_view.all_labels.options = labels
            self.data_view.make_label_result_text.value = f'Labeled {len(labels)} samples. | Min len: {minlen} | Max len: {maxlen}'
        
    def make_all_labels(self):
        labels = []
        only_validated = self.data_view.only_validated.value
        for i,(sample,validated) in enumerate(self.data_model.sample_series):
            if only_validated and (not validated):
                continue
            labels.append(self.build_label(i)) 
        return labels
    
    def sync_to_prepare_cb(self,event):
        for key,value in self.data_view.pipette_params['prepare'].items():
            self.data_view.pipette_params['load'][key].value = value.value
    
    def reset_uuid_cb(self,event):
        self.data_model.uuids = []
        self.data_view.uuid_list.options = []
    
    def update_sort_order_cb(self,event,direction):
        #selected = self.data_view.protocol_order.get_interact_value()
        selected = self.data_view.protocol_order.index
        if not selected:
            return
        
        #first grab list of options and find index of entry that is moving
        options = list(self.data_view.protocol_order.options)
        
        index = selected[0]
        if (index+direction>=len(options)):
            return
        elif (index+direction<0):
            return
        
        #store entry that is moving, and then delete it from list
        value_to_move = options[index]
        del options[index]
        
        #reinsert entry at new loc
        options.insert(index+direction,value_to_move)
        self.data_view.protocol_order.options = options
        self.data_view.protocol_order.index = (index+direction,)
        
    def make_mixing_wells(self):
        all_locs = []
        for wellspec in self.data_view.mixing_wells:
            slot = wellspec['slot'].value
            if slot<=0:
                all_locs.append([])
                continue
            nrows = wellspec['nrows'].value
            ncols = wellspec['ncols'].value
            start = wellspec['start'].value
            locs = AFL.automation.prepare.make_locs(slot,nrows,ncols)[start:]
            all_locs.append(locs)
        return all_locs
        
    def update_mixing_well_preview_cb(self,event):
        all_locs = self.make_mixing_wells()
        for locs,wellspec in zip(all_locs,self.data_view.mixing_wells):
            if not locs:
                continue
            wellspec['preview'].value =  f'{locs[0]} --> {locs[-1]}'
        
    def submit_mixing_wells_cb(self,event):
        all_locs = self.make_mixing_wells()
        all_locs = list(itertools.chain.from_iterable(all_locs))
        ip,port = self.data_view.robot_server_ip.value.split(':')
        client = Client(ip,port=port)
        client.login('WidgetGUI')
        client.debug(False)
        client.enqueue(task_name='add_prep_targets',
             targets=all_locs,
             reset=True,
            )
        
    def start(self):
        components = self.data_model.components
        nsamples = self.data_model.nsamples
        stock_names = [stock.name for stock in self.data_model.deck.stocks]
        widget = self.data_view.start(components,nsamples,stock_names)
        
        for component_name,spec in self.data_view.label_spec.items():
            spec['include'].observe(self.example_label_cb,names=['value'])
            if component_name=='prefix':
                spec['value'].observe(self.example_label_cb,names=['value'])
            elif component_name=='strip':
                spec['value'].observe(self.example_label_cb,names=['value'])
            elif component_name=='separator':
                spec['value'].observe(self.example_label_cb,names=['value'])
            else:
                spec['component_string'].observe(self.example_label_cb,names=['value'])
                spec['string_spec'].observe(self.example_label_cb,names=['value'])
                spec['units'].observe(self.example_label_cb,names=['value'])
                
        for wellspec in self.data_view.mixing_wells:
            for name,item in wellspec.items():
                if name == 'preview':
                    continue
                item.observe(self.update_mixing_well_preview_cb,names=['value'])
        
        self.data_view.sample_index.observe(self.example_label_cb,names=['value'])
        self.example_label_cb(None)
        
        self.data_view.up_button.on_click(lambda x: self.update_sort_order_cb(x,-1))
        self.data_view.down_button.on_click(lambda x: self.update_sort_order_cb(x,+1))
        
        self.data_view.label_button.on_click(self.make_all_labels_cb)
        self.data_view.pipette_load_sync.on_click(self.sync_to_prepare_cb)
        self.data_view.reset_uuid_button.on_click(self.reset_uuid_cb)
        
        self.data_view.apply_order_button.on_click(self.apply_protocol_order_cb)
        self.data_view.protocol_index.observe(self.update_protocol_order_preview_cb,names=['value'])
        
        self.data_view.mixing_wells_submit_button.on_click(self.submit_mixing_wells_cb)
        self.data_view.submit_jobs.on_click(self.submit_cb)
        return widget
    
    
class SampleSeriesWidget_Model:
    def __init__(self,deck):
        self.deck = deck
        self.sample_series = deck.sample_series
        self.components,_,_ = deck.get_components()
        self.nsamples = len(deck.sample_series.samples)
        self.uuids = []
        
    def adjust_protocol_order(self,mix_order):
        adjusted_protocols = []
        mix_order_map = {loc:new_index for new_index,(stock,loc) in enumerate(mix_order)}
        for sample,validated in self.deck.sample_series:
            if not validated:
                continue
            old_protocol = sample.protocol
            ordered_indices = list(map(lambda x: mix_order_map.get(x.source),sample.protocol))
            argsort = np.argsort(ordered_indices)
            new_protocol = list(map(sample.protocol.__getitem__,argsort))
            sample.protocol = new_protocol
            adjusted_protocols.append([old_protocol,new_protocol])
        return adjusted_protocols
    
class SampleSeriesWidget_View:
    def __init__(self):
        self.pipette_params = {}
        
    def make_component_grid(self,components,nsamples):
        self.component_grid_nrows = len(components)
        self.component_grid_ncols = 5
        text_width='100px'
        layout = ipywidgets.Layout(
            #grid_template_columns='10px '+(text_width+' ')*(self.component_grid_ncols-1),
            #grid_template_rows='20px'*self.component_grid_nrows,
            grid_gap='0px',
            max_width='500px',
        )
        component_grid = ipywidgets.GridspecLayout( 
            n_rows=self.component_grid_nrows+1, 
            n_columns=self.component_grid_ncols,
            layout=layout,
        )
        
        component_grid[0,0] = ipywidgets.Label(value='Include',layout=Layout(width='45px'))
        component_grid[0,1] = ipywidgets.Label(value='Component',layout=Layout(width=text_width))
        component_grid[0,2] = ipywidgets.Label(value='String',layout=Layout(width=text_width))
        component_grid[0,3] = ipywidgets.Label(value='Amount Spec',layout=Layout(width=text_width))
        component_grid[0,4] = ipywidgets.Label(value='units',layout=Layout(width=text_width))
         
        i = 1
        self.label_spec = {}
        for component in components:
            component_grid[i,0] = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False,value=True)
            #component_grid[i,1] = ipywidgets.Text(value=component,disabled=True,layout=Layout(width=text_width))
            component_grid[i,1] = ipywidgets.Label(value=component)
            component_grid[i,2] = ipywidgets.Text(value=component,layout=Layout(width=text_width))
            component_grid[i,3] = ipywidgets.Text(value='{:4.1f}',layout=Layout(width=text_width))
            component_grid[i,4] = ipywidgets.Text(value='mg/ml',layout=Layout(width=text_width))
            
            self.label_spec[component] = {}
            self.label_spec[component]['include']  = component_grid[i,0]
            self.label_spec[component]['component_string'] = component_grid[i,2]
            self.label_spec[component]['string_spec'] = component_grid[i,3]
            self.label_spec[component]['units'] = component_grid[i,4]
            i+=1
        
        prefix_check = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False,value=True)
        prefix_text = ipywidgets.Text(description='Prefix:',value='')
        
        self.label_spec['prefix'] = {}
        self.label_spec['prefix']['include']  = prefix_check
        self.label_spec['prefix']['value'] = prefix_text
        
        strip_check = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False,value=False)
        strip_label = ipywidgets.Label(value='Characters to Strip:')
        strip_text = ipywidgets.Text(value='/\\')
        
        self.label_spec['strip'] = {}
        self.label_spec['strip']['include']  = strip_check
        self.label_spec['strip']['value'] = strip_text
        
        separator_check = ipywidgets.Checkbox(layout=Layout(width='35px'),indent=False,value=False)
        separator_label = ipywidgets.Label(value='Separator:')
        separator_text = ipywidgets.Text(value=':')
        
        self.label_spec['separator'] = {}
        self.label_spec['separator']['include']  = separator_check
        self.label_spec['separator']['value'] = separator_text
        
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
        ])
        
        label_hbox = HBox([
            self.sample_index,
            sample_label_label,
            self.sample_label
        ])
        prefix_hbox = HBox([prefix_check,prefix_text])
        strip_hbox = HBox([strip_check,strip_label,strip_text])
        separator_hbox = HBox([separator_check,separator_label,separator_text])
        vbox = VBox([
            component_grid,
            prefix_hbox,
            strip_hbox,
            separator_hbox,
            label_hbox,box,
            self.all_labels,
            self.make_label_result_text
        ])
        
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
            
    def make_mixing_wells(self):
        
        label1 = Label('Deck Slot')
        label2 = Label('Num. Rows')
        label3 = Label('Num. Cols')
        label4 = Label('Start Index')
        label5 = Label('Preview')
        
        deck_slot_vbox = []
        deck_nrows_vbox = []
        deck_ncols_vbox = []
        deck_start_vbox = []
        deck_preview_vbox = []
        self.mixing_wells = []
        for i in range(4):
            self.mixing_wells.append({
                'slot':IntText(value=0,layout={'width':'75px'}),
                'nrows':IntText(value=8,layout={'width':'75px'}),
                'ncols':IntText(value=12,layout={'width':'75px'}),
                'start':IntText(value=0,layout={'width':'75px'}),
                'preview':Label(value=''),
            })
            
            deck_slot_vbox.append(self.mixing_wells[-1]['slot'])
            deck_nrows_vbox.append(self.mixing_wells[-1]['nrows']) 
            deck_ncols_vbox.append(self.mixing_wells[-1]['ncols']) 
            deck_start_vbox.append(self.mixing_wells[-1]['start'])
            deck_preview_vbox.append(self.mixing_wells[-1]['preview'])
            
        hbox = HBox([
            VBox([label1]+deck_slot_vbox),
            VBox([label2]+deck_nrows_vbox),
            VBox([label3]+deck_ncols_vbox),
            VBox([label4]+deck_start_vbox),
            VBox([label5]+deck_preview_vbox),
        ])
        
        self.robot_server_ip = Text(value='piot2:5000')
        self.mixing_wells_submit_button = Button(description='Add Wells')
        #self.mixing_wells_reset_button = Button(description='Reset Wells')
        #button_hbox = HBox([ self.mixing_wells_submit_button, self.mixing_wells_reset_button])
        button_hbox = HBox([ self.mixing_wells_submit_button])
        vbox = VBox([
            hbox,
            self.robot_server_ip,
            button_hbox,
        ])
        return vbox
        
        
    def start(self,components,nsamples,stock_names):
        mixing_well_tab = self.make_mixing_wells()
        
        component_grid = self.make_component_grid(components,nsamples)
        pipette_prepare_params = self.make_pipette_params('prepare')
        pipette_load_params = self.make_pipette_params('load')
        self.pipette_load_sync = Button(description="Sync to Prepare")
        load_volume_label = Label("Load Volume (uL)")
        self.load_volume = FloatText(value=300)
        load_volume_hbox = HBox([load_volume_label,self.load_volume])
        pipette_load_vbox = VBox([self.pipette_load_sync,load_volume_hbox,pipette_load_params])
        
        self.protocol_order = ipywidgets.SelectMultiple(
            options=stock_names,
            layout={'width':'400px'},
        )
        self.up_button = ipywidgets.Button( description='ꜛ')
        self.down_button = ipywidgets.Button(description='ꜜ')
        self.apply_order_button = ipywidgets.Button(description='Apply Ordering')
        vbox1 = VBox([self.up_button,self.down_button])
        protocol_hbox1 = HBox([self.protocol_order,vbox1])
        self.protocol_index = ipywidgets.BoundedIntText(min=0,max=nsamples-1,value=0,layout={'width':'50px'})
        index_label = Label("Protocol Number:")
        self.protocol_order_preview1= ipywidgets.SelectMultiple(options=[], layout={'width':'400px'} )
        self.protocol_order_preview2= ipywidgets.SelectMultiple(options=[], layout={'width':'400px'} )
        label1 = Label('Old Protocol')
        label2 = Label('New Protocol')
            
        protocol_hbox2 = HBox([index_label,self.protocol_index])
        protocol_hbox3 = HBox([VBox([label1,self.protocol_order_preview1]),VBox([label2,self.protocol_order_preview2])])
        
        order_box = VBox([protocol_hbox1,self.apply_order_button,protocol_hbox2,protocol_hbox3])
        
        exposure_time_label = Label("Exposure Time (s)")
        self.exposure_time = FloatText(value=10)
        self.shuffle_jobs = Checkbox(description='Shuffle',indent=False,value=True)
        self.sample_server_ip = Text(value='localhost:5000')
        self.submit_jobs = Button(description='Submit')
        self.submit_progress = ipywidgets.IntProgress(min=0,max=1,value=1)
        self.reset_uuid_button = Button(description='Reset UUIDS')
        self.uuid_list = ipywidgets.SelectMultiple(layout={'width':'400px'})
        submit_box = VBox([
            HBox([exposure_time_label,self.exposure_time]),
            self.shuffle_jobs,
            self.sample_server_ip,
            HBox([self.submit_jobs,self.submit_progress]),
            self.uuid_list,
            self.reset_uuid_button
        ])
        
        self.tabs = ipywidgets.Tab([
            mixing_well_tab,
            component_grid,
            pipette_prepare_params,
            pipette_load_vbox,
            order_box,
            submit_box
        ])
        self.tabs.set_title(0,'Mixing Wells')
        self.tabs.set_title(1,'Label Maker')
        self.tabs.set_title(2,'Prepare Params')
        self.tabs.set_title(3,'Load Params')
        self.tabs.set_title(4,'Protocol Order')
        self.tabs.set_title(5,'Submit')
        
        return self.tabs
    
