import ipywidgets as widgets
import functools

from IPython.display import display, Markdown, clear_output
# widget packages


def _ignoreargs(func, count):
    @functools.wraps(func)
    def newfunc(*args, **kwargs):
        return func(*(args[count:]), **kwargs)
    return newfunc


def client_construct_ui(self,return_ui=False,display_ui=True):
    qb = self.get_quickbar()
    panel = {}
    for entry in qb:
        function_name = entry
        try:
            button_text = qb[entry]["qb"]["button_text"]
        except KeyError:
            button_text = function_name
        try:
            params = qb[entry]["qb"]["params"]
        except KeyError:
            params = {}
        
        panel[entry] = {}
        
        if len(params)==0:
            #print(f'Adding button for function {function_name} with text: {button_text}')
            panel[entry]['button'] = widgets.Button(description=button_text)
            panel[entry]['button'].on_click(functools.partial(_ignoreargs(self.enqueue,1),task_name=function_name,interactive=False))
        else:
            inputlist = []
            for param in params:
                kwarg_name=param
                try:
                    field_label = params[param]['label']
                except KeyError:
                    field_label = param
                try:
                    default = params[param]['default']
                except KeyError:
                    default = 0
                try:
                    dtype = params[param]['type']
                except KeyError:
                    dtype = 'text'
                #print(f'Adding field for kwarg name {kwarg_name}, labeled {field_label}, type {dtype} and default value {default}')
                if dtype == 'float':
                    panel[entry][kwarg_name] = widgets.FloatText(
                                            value=default,
                                            description=field_label,
                                            disabled=False
                                        )
                elif dtype=='int':
                    panel[entry][kwarg_name] = widgets.IntText(
                                            value=default,
                                            description=field_label,
                                            disabled=False
                                        )
                elif dtype=='bool':
                    panel[entry][kwarg_name] = widgets.Checkbox(
                                            value=bool(default),
                                            description=field_label,
                                            disabled=False
                                        )    

                else: #also catch 'text'
                    panel[entry][kwarg_name] = widgets.Text(
                                            value=default,
                                            description=field_label,
                                            disabled=False
                                        )                    
                panel[entry][kwarg_name].kwarg_name = kwarg_name
                inputlist.append(panel[entry][kwarg_name])
            #print(f'Adding button for function {function_name} with text: {button_text} and above params.')
            input_func_kwargs = lambda inputlist: {ip.kwarg_name:ip.value for ip in inputlist}
            panel[entry]['button'] = widgets.Button(description=button_text)
            panel[entry]['button'].on_click(functools.partial(_ignoreargs(self.enqueue,1),task_name=function_name,interactive=False,params=functools.partial(input_func_kwargs,inputlist=inputlist)))
        panel[entry]['vbox'] = widgets.VBox(list(panel[entry].values()))
    panel['hbox'] = widgets.HBox([panel[entry]['vbox'] for entry in panel],layout={'flex-flow': 'flex-wrap','width':'80%'})  
    if display_ui:
        display(panel['hbox'])  
    if return_ui:   
        return panel