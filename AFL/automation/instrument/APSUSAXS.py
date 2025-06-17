import gc
import time
import datetime
from AFL.automation.APIServer.Driver import Driver
import numpy as np # for return types in get data
import h5py #for Nexus file reading
import lazy_loader as lazy
epics = lazy.load("epics", require="AFL-automation[neutron-scattering]")
import os
import pathlib
import warnings
Matilda = lazy.load("Matilda", require="AFL-automation[usaxs]")

class APSUSAXS(Driver):
    defaults = {}
    defaults['sample_thickness'] = 1.58
    defaults['run_initiate_pv'] = '9idcLAX:AutoCollectionStart'
    defaults['script_name_pv'] = '9idcLAX:AutoCollectionStrInput'
    defaults['instrument_status_pv'] = '9idcLAX:state'
    defaults['script_path'] = '/mnt/share1/USAXS_data/2022-06/'
    defaults['instrument_running_pv'] = '9idcLAX:dataColInProgress'
    defaults['script_template_file'] = 'AFL-template.mac'
    defaults['script_file'] = 'AFL.mac'
    defaults['magic_project_key'] = '!!AFL-SETNAME!!'
    defaults['magic_filename_key'] = '!!AFLREPLACEME!!'
    defaults['magic_xpos_key'] = '!!AFLXPOS!!'
    defaults['magic_ypos_key'] = '!!AFLYPOS!!'
    defaults['active_holder'] = '6A'
    defaults['script_write_cooldown'] = 1 
    defaults['platemap'] = {
                         '6A':{
                     'SlotA':
                        {
                          'x0': 0,
                          'y0': 0,
                          'x_step': 9,
                          'y_step': 9,
                          'x_per_y_skew': .5,
                          'y_per_x_skew': -(8/12)*.5,
                        },
                        'SlotB':
                        {
                          'x0': -150,
                          'y0': -150,
                          'x_step': 9,
                          'y_step': 9,
                          'x_per_y_skew': 1,
                          'y_per_x_skew': -(8/12)*1,
                        },
                        'SlotC':
                        {
                          'x0': 150,
                          'y0': 150,
                          'x_step': 9,
                          'y_step': 9,
                          'x_per_y_skew': -8,
                          'y_per_x_skew': -(8/12)*-8,
                        },

                    }
                    }
    defaults['empty_scan_title'] = ''
    defaults['USAXS_mode'] = 'Flyscan' #Flyscane or uascan
    defaults['USAXS_npts'] = 400
    defaults['USAXS_signal_cutoff'] = 1.05

    def __init__(self,overrides=None):
        '''
        connect to usaxs via EPICS

        '''

        self.convertUSAXS = lazy.load("Matilda.convertUSAXS", require="AFL-automation[usaxs]")
        self.convertSAS = lazy.load("Matilda.convertSAS", require="AFL-automation[usaxs]")
        self.readfromtiled = lazy.load("Matilda.readfromtiled", require="AFL-automation[usaxs]")

        self.app = None
        Driver.__init__(self,name='APSUSAXS',defaults=self.gather_defaults(),overrides=overrides)
        
        
        self.__instrument_name__ = 'APS USAXS instrument'
        
        self.status_txt = 'Just started...'
        self.filename = 'default'
        self.project = 'AFL'
        self.xpos = 0
        self.ypos = 0

    def pre_execute(self,**kwargs):
        pass


        
    @Driver.unqueued()
    def getFilename(self):
        '''
            get the currently set file name

        '''
        return self.filename


    def setFilename(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        self.filename = name
    @Driver.unqueued()
    def getProject(self):
        '''
           get the currently set file name
        
        '''
        return self.project

    def _coords_from_tuple(self,slot,row,col):
        if len(row)>1:
            raise ValueError('row must be a single letter')
        row = ord(row) & 31
        col = int(col)

        geom = self.config['platemap'][self.config['active_holder']][slot]

        return (geom['x0'] + (row-1)*geom['x_step'] + geom['x_per_y_skew']*(col-1),
                geom['y0'] + (col-1)*geom['y_step'] + geom['y_per_x_skew']*(row-1))
    
    def setProject(self,name):
        if self.app is not None:
            self.app.logger.debug(f'Setting filename to {name}')

        self.project = name

    def _writeUSAXSScript(self):
        '''
        burn the current filename and project name into a USAXS script
        '''

        lines = []
        with open(pathlib.Path(self.config['script_path'])/self.config['script_template_file'],'r') as f:
            for line in f:
                s = line.replace(self.config['magic_project_key'],self.project)
                s = s.replace(self.config['magic_filename_key'],self.filename)
                s = s.replace(self.config['magic_xpos_key'],str(self.xpos))
                s = s.replace(self.config['magic_ypos_key'],str(self.ypos))
                s = s.replace('\r','')
                s = s.replace('\n','')
                lines.append(s)
        with open(pathlib.Path(self.config['script_path'])/self.config['script_file'],'w') as f:
            for line in lines:
                f.write(line+'\r\n')

    @Driver.quickbar(qb={'button_text':'Expose',
        'params':{
        'name':{'label':'Name','type':'text','default':'test_exposure'},
        'exposure':{'label':'Exposure (s)','type':'float','default':5},
        'reduce_data':{'label':'Reduce?','type':'bool','default':True},
        'measure_transmission':{'label':'Measure Trans?','type':'bool','default':True}
        }})
    def expose(self, name = None, block = True, reduce_USAXS = True, reduce_WAXS = True):
        if name is None:
            name=self.getFilename()
        else:
            self.setFilename(name)
        self.status_txt = f'Starting USAXS/SAXS/WAXS scan named {name}'
        if self.app is not None:
            self.app.logger.debug(f'Starting USAXS/SAXS/WAXS exposure with name {name}')
        self.status_txt = 'Writing script...'
        self._writeUSAXSScript()
        self.status_txt = 'Waiting for script save...'
        time.sleep(self.config['script_write_cooldown'])
        epics.caput(self.config['script_name_pv'],self.config['script_file'])
        time.sleep(0.1)
        epics.caput(self.config['run_initiate_pv'],1)
        self.status_txt = 'Run started!'

        time.sleep(0.5)
        if block or reduce_data:
            time.sleep(20)
            self.block_for_run_finish()
            self.status_txt = 'Instrument Idle'
            
        if reduce_USAXS:
           # get last flyscan from Tiled and check that the set filename matches the found file
           [last_scan_path, last_scan_file] = self.readfromtiled.FindLastScanData('Flyscan',1)[0]
           if name.replace('-','_') not in last_scan_file:
                   raise ValueError(f"Did not get data that seemed to match, you collected {name}, we got {last_scan_file}")

           # reduce flyscan data
           last_scan_results = self.convertUSAXS.reduceFlyscanToQR(last_scan_path,last_scan_file)
           results_ds = self.convertUSAXS.results_to_dataset(last_scan_results)
           USAXS_int = results_ds['USAXS_int']

           # get empty flyscan, reduce it
           [empty_path,empty_file] = self.readfromtiled.FindScanDataByName('Flyscan',self.config['empty_scan_title'])[0]
           empty_results = self.convertUSAXS.reduceFlyscanToQR(empty_path,empty_file)
           empty_ds = self.convertUSAXS.results_to_dataset(empty_results)
           MT_USAXS_int = empty_ds['USAXS_int']
           MT_USAXS_int = MT_USAXS_int.interp_like(USAXS_int) #interpolate to match last scan

           # determine minimum q; argmax because we're looking for the first True (which is cast to be 1)
           qmin_index = np.argmax((USAXS_int.values/MT_USAXS_int.values)>float(self.config['USAXS_signal_cutoff']))
           qmin = USAXS_int['q'].isel(q=qmin_index).item()
           
           #interpolate
           new_q = np.geomspace(qmin,USAXS_int['q'].max(),self.config['USAXS_npts'])
           USAXS_int = USAXS_int.interp(q=new_q)
           MT_USAXS_int = MT_USAXS_int.interp(q=new_q)

           # background subtraction
           peaktopeak_T = (results_ds.Maximum / empty_ds.Maximum)
           USAXS_sub = 1/peaktopeak_T * USAXS_int - MT_USAXS_int

           # add data to tiled
           self.data.add_array('USAXS_q',USAXS_int['q'].values)
           self.data.add_array('USAXS_int',USAXS_int.values)
           self.data.add_array('USAXS_sub',USAXS_sub.values)
           self.data.add_array('MT_USAXS_q',MT_USAXS_int['q'].values)
           self.data.add_array('MT_USAXS_int',MT_USAXS_int.values)
           self.data['USAXS_Filepath'] = last_scan_path
           self.data['USAXS_Filename'] = last_scan_file
           self.data['USAXS_transmission'] = peaktopeak_T
           
        if reduce_WAXS: 
           # get last WAXS from Tiled, reduce it
           [last_scan_path, last_scan_file] = self.readfromtiled.FindLastScanData('WAXS',1)[0]
           if name.replace('-','_') not in last_scan_file:
                   raise ValueError(f"Did not get data that seemed to match, you collected {name}, we got {last_scan_file}")
           #reduce
           last_scan_results = self.convertSAS.ImportAndReduceAD(last_scan_path,last_scan_file)
           
           # add data to tiled
           self.data.add_array('WAXS_q',last_scan_results['Q_array'])
           self.data.add_array('WAXS_int',last_scan_results['Intensity'])
           self.data['WAXS_Filepath'] = last_scan_path
           self.data['WAXS_Filename'] = last_scan_file

    def block_for_run_finish(self):
        while self.getRunInProgress():
            time.sleep(5)
        
    def getRunStatus(self):
        return epics.caget(self.config['instrument_status_pv'],as_string=True)
    
    def setPosition(self,plate,row,col,x_offset=0,y_offset=0):
        (self.xpos,self.ypos) = self._coords_from_tuple(plate,row,col)
        self.xpos+=x_offset
        self.ypos+=y_offset
        
    def getRunInProgress(self):
        return epics.caget(self.config['instrument_running_pv']) 
    
               
    def status(self):
        status = []
        status.append(f'Status: {self.status_txt}')
        status.append(f'EPICS status: {self.getRunStatus()}')
        status.append(f'Next X: {self.xpos}')
        status.append(f'Next Y: {self.ypos}')
        status.append(f'Next filename: {self.filename}')
        status.append(f'Next project: {self.project}')
        return status
if __name__ == '__main__':
    from AFL.automation.shared.launcher import *


