from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import time
import logging
import datetime

class FileChangeHandler(PatternMatchingEventHandler):
    def __init__(self,fname,callback,cooldown,logger):
        super().__init__(patterns=[f'*/{fname}'])
        self.callback = callback
        self.cooldown = datetime.timedelta(seconds=cooldown)
        self.last_call = datetime.datetime.now()-self.cooldown #make sure first call happens
        self.logger = logger
        
    def on_modified(self, event):
        if (datetime.datetime.now()-self.last_call)>=self.cooldown:
            self.logger.info(f'Watchdog triggered with event: {event}')
            self.last_call = datetime.datetime.now()
            self.callback()

class WatchDog:
    def __init__(self,path,fname,callback,cooldown):
        self.logger = logging.getLogger()
        self.event_handler = FileChangeHandler(fname=fname,callback=callback,cooldown=cooldown,logger=self.logger)
        self.observer = Observer()
        self.path = path
        self.fname = fname
        
    def start(self):
        self.observer.schedule(self.event_handler, path=self.path)
        self.logger.info('Starting WatchDog on dir {self.path} and file {self.fname}')
        self.observer.start()
        
    def stop(self):
        self.observer.stop()
        self.observer.join()
        self.logger.info('Stopping WatchDog')
        
