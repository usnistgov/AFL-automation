import math

class Tubing():
    tubing = [{'typeid':1530,'material':'Tefzel','IDEXpart':1530,'OD_in':0.125, 'ID_mm':1.575},
            {'typeid':1529,  'material':'Tefzel','IDEXpart':1529,'OD_in':0.075, 'ID_mm':0.254},
            {'typeid':1,     'material':'PVC',   'IDEXpart':0,   'OD_in':0.1875,'ID_mm':2.92},
            {'typeid':1517,  'material':'Tefzel','IDEXpart':1517,'OD_in':0.075, 'ID_mm':1}]

    def __init__(self,specid,length):
        '''
        length is in cm?
        '''
        for tubingtype in Tubing.tubing:
            if tubingtype['typeid'] == specid:
                self.id_mm    = tubingtype['ID_mm']
                self.od_in    = tubingtype['OD_in']
                self.idexpart = tubingtype['IDEXpart']
                self.material     = tubingtype['material']
                self.length   = length
                return
        raise NotImplementedError
    
    def volume(self):
        '''returns volume in mL'''
        return (self.id_mm / 20)**2 *math.pi*self.length
