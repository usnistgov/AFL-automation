====================
Quick Start Guide
====================

This quick start guide will help you get up and running with AFL-automation quickly.

Creating Your First Driver
-------------------------

AFL-automation is built around the concept of *drivers* - Python classes that interact with hardware or provide services. Here's a simple example:

.. code-block:: python

    from AFL.automation.APIServer.Driver import Driver
    
    class SimpleDriver(Driver):
        defaults = {}
        defaults['greeting'] = 'Hello, World!'
        
        def __init__(self, overrides=None):
            Driver.__init__(self, name='SimpleDriver', 
                           defaults=self.gather_defaults(),
                           overrides=overrides)
        
        def say_hello(self):
            """Say a greeting based on configuration"""
            return self.config['greeting']

Running as a Microservice
------------------------

Once you have a driver, you can turn it into a web service:

.. code-block:: python

    from AFL.automation.APIServer.APIServer import APIServer
    
    # Create the driver instance
    my_driver = SimpleDriver()
    
    # Create the server
    server = APIServer('my-service')
    
    # Add your driver and run the server
    server.create_queue(my_driver)
    server.run(host='0.0.0.0', port=5000)

We usually run the server using a short-hand module called :mod:`AFL.automation.shared.launcher`. 
This requires two lines of boilerplate code at the end of your driver, like so.  
It also requires the module (i.e, the Python file your driver is in) to be named the same as the Driver name.

.. code-block:: python
    
    from AFL.automation.APIServer.Driver import Driver
    
    class SimpleDriver(Driver):
        defaults = {}
        defaults['greeting'] = 'Hello, World!'
        
        def __init__(self, overrides=None):
            Driver.__init__(self, name='SimpleDriver', 
                           defaults=self.gather_defaults(),
                           overrides=overrides)
        
        def say_hello(self):
            """Say a greeting based on configuration"""
            return self.config['greeting']

    if __name__ == '__main__':
        from AFL.automation.shared.launcher import *

Once you have these magic lines in your Driver, you can simply invoke the server as a Python module from the command line:
 .. code-block:: bash
    python -m SimpleDriver
    
or for a built-in driver, for instance SeabreezeUVVis:

.. code-block:: bash
    python -m AFL.automation.instrument.SeabreezeUVVis

Accessing the Service (API)
-------------------------------

You can now access your service via HTTP requests or use the built-in client:

.. code-block:: python

    from AFL.automation.APIServer.Client import Client
    
    # Connect to the service
    client = Client('http://localhost:5000')
    
    # Call a method
    response = client.enqueue(task_name='say_hello',interactive=True)
    print(response)  # Outputs: 'Hello, World!'

    # Call a method asynchronously
    response = client.enqueue(task_name='say_hello',interactive=False)
    print(response)  # Outputs a uuid

    # Get the result of the task
    result = client.get_result(response)
    print(result)  # Outputs: 'Hello, World!'

Accessing the Service (Browser)
--------------------------------

You also get a browser-based user interface, accessible by simply pointing a browser to http://localhost:5000

Using this interface, you can view the driver status, call methods that are labeled as quickbar methods, pause/unpause the queue, and set configuration items.


Next Steps
---------

For more detailed instructions, check out:

- :doc:`/explanation/architecture` - Learn about AFL-automation's architecture
- :doc:`/how-to/dependencies` - Manage hardware-specific dependencies
- API Reference - Explore the full API documentation
