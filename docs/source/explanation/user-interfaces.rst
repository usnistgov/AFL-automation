===============================================
AFL-automation Autogenerated User Interfaces
===============================================

This page explains the features in AFL-automation that enable the generation of user interfaces for Drivers without specific code.


Core Concepts
-------------

1. **Unqueued Functions**

Conceptually, the functions of a driver are classified as either **queued** or **unqueued**. The delineating line is whether the funcion changes state.
For example, if the function moves hardware, that should almost always be queued.
If the function just fetches data from hardware non-destructively, or reports state, that is a candidate for unqueued.

**Unqueued** functions are advertised as server routes. Conceptually, this means that a function called `how_many` can be decorated like so:

.. code-block:: python

        @Driver.unqueued()
        def how_many(self,**kwargs):
            self.app.logger.debug(f'Call to how_many with kwargs: {kwargs}')
            if 'count' in kwargs:
                return f'Not sure, but probably something like {kwargs["count"]}'
            else:
                return "Not sure"
    
This, rather simple, function, will be turned into a **URL endpoint** that accepts HTTP GET requests, such that navigating to http://server/how_many will display "Not sure", and navigating to http://server/how_many?count=5 will display "Not sure, but probably something like 5"

OK, that is a silly example.

Try this one, though:

.. code-block:: python

        @Driver.unqueued(render_hint='1d_plot',xlin=True,ylin=True,xlabel="random x",ylabel="random y",title="random data")
        def test_plot(self,**kwargs):
            self.app.logger.debug(f'Call to test_plot with kwargs: {kwargs}')
            return (np.random.rand(500,2))


        @Driver.unqueued(render_hint='2d_img',log_image=True)
        def test_image(self,**kwargs):
            return np.random.rand(1024,1024)

You can provide a `render_hint` that will tell the APIServer to prepare the data in a certain way, for instance serving a Bokeh plot or a jpg image.

Valid values of `render_hint` are ['raw','precomposed_svg','precomposed_jpg','1d_plot','2d_img']

The other kwargs can be provided in the function decorator, but will be overridden with URL arguments, so the user can change the plot from log to lin (say) from the client.

.. note::

   Unqueued functions are served via HTTP ``GET`` routes and are intended for
   read-only queries.  Any action that modifies state must be submitted to the
   server's ``/enqueue`` endpoint using a ``POST`` request with a valid JWT
   token obtained from ``/login``.  A common pattern is for a user interface to
   stage changes locally and then send them as one queued task, rather than
   calling unqueued endpoints with ``POST``.



2. **Quickbar Decorator**

Similar to `@Driver.unqueued`, there is a decorator `@Driver.quickbar`. This is used to generate hints for clients to make user interfaces.

For example:

.. code-block:: python

        @Driver.quickbar(qb={'button_text':'Load Sample',
                            'params':{
                                'sampleVolume':{
                                    'label':'Sample Volume (mL)',
                                    'type':'float',
                                    'default':0.3
                                            }}})
        def loadSample(self,cellname='cell',sampleVolume=0):
        pass

A bit long-winded? Sure.
But this syntax tells a client that this function can be called, using a button labeled "Load Sample", and takes a parameter as described, with a default value.

Quickbar functions appear on the html status page of the server, and can be ingested by other user interfaces such as ipywidgets in a notebook.

Serving Additional Static Files
-------------------------------

If your driver requires custom JavaScript or images, define a ``static_dirs``
class attribute mapping subpaths to directories::

    class MyDriver(Driver):
        static_dirs = {
            'js': pathlib.Path(__file__).parent / 'js',
            'img': pathlib.Path(__file__).parent / 'images',
        }

The APIServer will automatically serve files from these directories at
``/static/js`` and ``/static/img``.
