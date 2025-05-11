import time
import datetime
import os
import pathlib
import uuid

import matplotlib
import numpy as np
import pandas as pd
import lazy_loader as lazy
# SAS modeling libraries only need lazy loading
import h5py #for Nexus file writing

# SAS modeling libraries
sasmodels = lazy.load("sasmodels", require="AFL-automation[sas-analysis]")

shapely = lazy.load("shapely", require="AFL-automation[geometry]")

from shapely import MultiPoint
from shapely.geometry import Point
from shapely import concave_hull

from AFL.automation.APIServer.Driver import Driver
from AFL.automation.shared.utilities import mpl_plot_to_bytes
from AFL.agent.util import ternary_to_xy
from AFL.agent.xarray_extensions import *


class VirtualSAS_theory(Driver):
    defaults = {}
    defaults['save_path'] = '/home/afl642/2305_SINQ_SANS_path'
    defaults['noise'] = 0.0
    defaults['ternary'] = False
    defaults['fast_locate'] = True
    defaults['old_components'] = False

    def __init__(self,overrides=None):
        '''
        Generates smoothly interpolated scattering data via a noiseless GPR from an experiments netcdf file
        '''
        self.app = None
        Driver.__init__(self,name='VirtualSAS_theory',defaults=self.gather_defaults(),overrides=overrides)
        
        import sasmodels.data
        import sasmodels.core
        import sasmodels.direct_model
        import sasmodels.bumps_model

        import shapely.MultiPoint
        import shapely.geometry.Point
        import shapely.concave_hull
        
        self.hulls = {}
        self.reference_data = []
        self.sasmodels = {}
        self.boundary_dataset = None
        
    def status(self):
        status = []
        status.append(f'Configurations Loaded={len(self.reference_data)}')
        status.append(f'Phases Traced={len(self.hulls)}')
        status.append(f'Noise Level={self.config["noise"]}')
        status.append(f'Ternary={self.config["ternary"]}')
        return status
    
    def trace_boundaries(self,hull_tracing_ratio=0.1,drop_phases=None,reset=True):
        if self.boundary_dataset is None:
            raise ValueError('Must set boundary_dataset before calling trace_boundaries! Use client.set_driver_object.')
            
        if drop_phases is None:
            drop_phases = []
        
        if reset:
            self.hulls = {}
        
        label_variable = self.boundary_dataset.attrs['labels']
        for label,sds in self.boundary_dataset.groupby(label_variable):
            if label in drop_phases:
                continue
            if self.config['old_components']:
                comps = sds[sds.attrs['components']].to_array('component').transpose(...,'component')
            else:
                comps = sds[sds.attrs['components']].transpose(..., 'component')
            if self.config['ternary']:
                xy = ternary_to_xy(comps.values[:,[2,0,1]]) #shapely uses a different coordinate system than we do
            else:
                xy = comps.values[:]
                assert xy.shape[1]==2, (
                    f'''Need to be in ternary mode with three components, or non-ternary with two. '''
                    f'''You  have "xy.shape:{xy.shape}" and ternary={self.config["ternary"]}'''
                    )
            mp = shapely.MultiPoint(xy)
            hull = shapely.concave_hull(mp,ratio=hull_tracing_ratio)
            self.hulls[label] = hull
    
    def locate(self,composition):
        composition = np.array(composition)

        if self.hulls is None:
            raise ValueError('Must call trace_boundaries before locate')
        if self.config['ternary']:
            xy = ternary_to_xy(composition)
        else:
            xy = composition
        point = shapely.Point(*xy)
        locations = {}
        for phase,hull in self.hulls.items():
            if hull.contains(point):
                locations[phase] = True
                if self.config['fast_locate']:
                    break
            else:
                locations[phase] = False
                
        if sum(locations.values())>1:
            warnings.warn('Location in multiple phases. Phases likely overlapping')
            
        phases = [key for key,value in locations.items() if value]
        self.data['locate_locations'] = locations
        self.data['locate_phases'] = phases
        return phases

    def add_configuration(self,q,I,dI,dq,reset=True):
        '''Read in reference data for an instrument configuration'''
        if reset:
            self.reference_data = []
        data = sasmodels.data.Data1D(
            x=np.array(q),
            y=np.array(I),
            dy=np.array(dI),
            dx=np.array(dq),
        )
        self.reference_data.append(data)
        
    def add_sasview_model(self,label,model_name,model_kw):
        calculators = []
        sasdatas = []
        for sasdata in self.reference_data:
            model_info    = sasmodels.core.load_model_info(model_name)
            kernel        = sasmodels.core.build_model(model_info)
            calculator    = sasmodels.direct_model.DirectModel(sasdata,kernel)
            calculators.append(calculator)
            sasdatas.append(sasdata)
            
        self.sasmodels[label] = {
            'name':model_name,
            'kw':model_kw,
            'calculators':calculators,
            'sasdata':sasdatas,
        }
        
    def generate(self,label):
        kw          = self.sasmodels[label]['kw']
        calculators = self.sasmodels[label]['calculators']
        sasdatas    = self.sasmodels[label]['sasdata']
        noise = self.config['noise']
        
        I_noiseless_list = []
        I_list = []
        dI_list = []
        for sasdata,calc in zip(sasdatas,calculators):
            I_noiseless = calc(**kw)
            
            dI_model = sasdata.dy*np.sqrt(I_noiseless/sasdata.y)
            mean_var= np.mean(dI_model*dI_model/I_noiseless)
            # dI = sasdata.dy*np.sqrt(noise*noise/mean_var)
            dI = sasdata.dy*noise/mean_var
            
            I = np.random.normal(loc=I_noiseless,scale=dI)
            
            I_noiseless = pd.Series(data=I_noiseless,index=sasdata.x)
            I = pd.Series(data=I,index=sasdata.x)
            dI = pd.Series(data=dI,index=sasdata.x)
            
            I_list.append(I)
            I_noiseless_list.append(I_noiseless)
            dI_list.append(dI)
            
        I           = pd.concat(I_list).sort_index()
        I_noiseless = pd.concat(I_noiseless_list).sort_index()
        dI          = pd.concat(dI_list).sort_index()
        return I,I_noiseless,dI
    
    def expose(self,*args,**kwargs):
        '''Mimic the expose command from other instrument servers'''

        if self.config['old_components']:
            components = self.boundary_dataset.attrs['components']
        else:
            components = self.boundary_dataset[self.boundary_dataset.attrs['components_dim']].values
        composition = [[self.data['sample_composition'][component]['value'] for component in components]] #from tiled

        phases = self.locate(composition)
        if len(phases)==0:
            label = 'D'
        elif len(phases)==1:
            label = phases[0]
        else:
            label = phases[0]
        
        I,I_noiseless,dI = self.generate(label)
        
        self.data['q'] = I.index.values
        self.data['components'] = components
        self.data.add_array('I',I.values)
        self.data.add_array('I_noiseless',I_noiseless.values)
        self.data.add_array('dI',dI.values)

        return I.values
    
            
    @Driver.unqueued(render_hint='precomposed_svg')
    def plot_hulls(self,**kwargs):
        matplotlib.use('Agg') #very important
        fig,ax = plt.subplots()
        if self.hulls is None:
            plt.text(1,5,'No hulls calculated. Run .trace_boundaries')
            plt.gca().set(xlim=(0,10),ylim=(0,10))
        else:
            for label,hull in self.hulls.items():
                plt.plot(*hull.boundary.xy)
        svg  = mpl_plot_to_bytes(fig,format='svg')
        return svg
    
    @Driver.unqueued(render_hint='precomposed_svg')
    def plot_boundary_data(self,**kwargs):
        matplotlib.use('Agg') #very important
        fig,ax = plt.subplots(subplot_kw={'projection':'ternary'})
        if self.hulls is None:
            plt.text(1,5,'No hulls calculated. Run .trace_boundaries')
            plt.gca().set(xlim=(0,10),ylim=(0,10))
        else:
            labels = self.boundary_dataset[self.boundary_dataset.attrs['labels']]
            self.boundary_dataset.afl.comp.plot_scatter(labels=labels,ax=ax)
        svg  = mpl_plot_to_bytes(fig,format='svg')
        return svg
    
    
    
