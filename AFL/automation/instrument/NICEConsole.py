import lazy_loader as lazy
# NIST NCNR NICE control system
nice = lazy.load("nice", require="AFL-automation[nice-neutron-scattering]")
import time

class NICEConsole(nice.api.console.ConsoleMonitor):
    def __init__(self,textbox):
        self.textbox = textbox
        
    def onSubscribe(self,history,current):
        self._history=history
        messages = []
        for event in history:
            m = self._parse_event(event)
            if m is None:
                continue
            messages.append(m)
        self.textbox.value = ''.join(messages)
            
    def report(self,event,current):
        m = self._parse_event(event)
        
        if m is None:
            return
        
        self.textbox.value += m
        
    def _parse_event(self,event):
        level = event.level._name
        if not (level in ('ERROR','CRITICAL','SERIOUS','IMPORTANT','INFO')):
            return None
        
        date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(event.timestamp/1e3))
        msg = event.message.replace('&quot;','"')
        msg = event.message.replace('\\"','"')
        event_str = '<p>{}> {}</p>'.format(date,msg)
        
        return event_str

