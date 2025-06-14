import threading
import warnings
from queue import Empty, Full
import time

class MutableQueue:
    '''Thread-safe, mutable queue
    
    Unlike the standard library CPython queue, this class supportes positional inserts, deletions, and reordering. The tradeoff is performance for both reads and writes to the queue.
    '''
    def __init__(self):
        # Queue storage object
        self.queue = list()
        
        # Lock must be held whenever the queue list is mutated
        self.lock = threading.Lock() 
        
        # Notify not_empty whenever an item is added to the queue; a
        # thread waiting to get is notified then.
        self.not_empty = threading.Condition(self.lock)

        self.iteration_id = time.time()
        
    def qsize(self):
        return len(self.queue)

    def iterationid(self):
        return self.iteration_id

    def empty(self):
        with self.lock:
            return not self.qsize()
        
    def _put(self,item,loc):
        self.queue.insert(loc,item)
        self.iteration_id = time.time()
            
    def _get(self,loc=0):
        self.iteration_id = time.time()
        return self.queue.pop(loc)
    
    def put(self,item,loc):
        '''Insert an item at the top of the queue'''
        with self.lock:
            self._put(item,loc)
            self.not_empty.notify()# notify any waiting threads
        
    def remove(self,loc):
        '''Remove an item from the queue'''
        with self.lock:
            self.iteration_id = time.time()
            if loc>=self.qsize():
                raise IndexError
            self._get(loc)
        
    def get(self,loc=0,block=True,timeout=None):
        '''Get next item from queue'''
        if timeout is not None:
            warnings.warn('Timeout is included for compatibility but is not implemented')

        with self.not_empty:#implies self.lock
            if not block and not self.qsize():
                raise Empty
            else:
                while not self.qsize():
                    self.not_empty.wait() #releases self.lock until notify
                    
            if loc>=self.qsize():
                raise IndexError

            return self._get(loc)
        
    def move(self,old_index,new_index=None):
        '''Move item in queue'''
        with self.lock:
            self.iteration_id = time.time()
            if new_index is None:
                new_index = self.qsize()
            
            if old_index<new_index:
                self.queue.insert(new_index+1,self.queue[old_index])
                del self.queue[old_index]
                
            elif old_index>new_index:
                self.queue.insert(new_index,self.queue[old_index])
                del self.queue[old_index+1]

    def clear(self):
        '''Remove all items from the queue'''
        with self.lock:
            self.queue.clear()
            self.iteration_id = time.time()
            
