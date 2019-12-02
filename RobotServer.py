
from opentrons import robot,containers,instruments       
class RobotServer:
    
    def __init__(self,robot,pipet1,pipet2=None)
        self.robot = robot
        self.pipet1 = pipet1
        self.pipet2 = pipet2
        self.deck = []
        self.containers = []
        
        
    def addToDeck(self,type,slot):
        self.deck[slot] = opentrons.containers.load(type,str(slot))
    
    def addNamedContainer(self,slot,well,name,volume,formula=None):
        self.containers.append() # @TODO: should containers be an object or just a dict?
        
    def makeSampleSet(self,sampleset):
         
        #step zero: make a list of all the components we need to make this whole sample set.
        
        allcomponentsneeded = []
        for sample in sampleset:
            for component in sample.components:
                if component.name not in allcomponentsneeded:
                    allcomponentsneeded.append(component)
        
        #important: order transfer so the most common component (highest volume, highest # transfers) is first. 
        
        
        
        
        #feasibility check and protocol construction: a) do we have a place to put the sample and b) do we have the ingredients we need to make this sample?
    
        for sample in sampleset:
            # get list of empty vials  (this could also be vials with a solid e.g. polymer pre-weighed in, this seems like a v2 issue)
            
            # assign next empty vial to sample.
            sample.location = None #replace none with next empty vial.
            
            # if no empty vials in robot, fail.
    
        for component in allcomponentsneeded:
            # search our containers for a match
            # could add some logic here about which container to use, e.g. use the container with lowest remaining volume that still satisfies the request.
            
            #if match:
                #check if enough remains to satisfy request.
                #add transfer (one-to-many for first component, one-to-one for subsequent components to avoid cross contamination) to run list
            #else:
                #fail
                
            #