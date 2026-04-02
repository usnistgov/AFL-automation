Beginner Guide
=====

This tutorial will guide you through basic examples of using the AFL through use of a raspberry pi. After going through this tutorial, you will learn:

- How to queue basic commands to the AFL and view the results
- How to queue hardware specific commands to the AFL and view the results
- How to set up external devices to be used with the AFL

Prerequisites
-----------------

To fully utilize this tutorial, a raspberry pi with internet access and the AFL installed is required. For how to install the AFL, please see :doc:`Setup <installation>`.

Basic AFL usage
---------------------------------

To get a good understanding of a basic use case of the AFL, consider the starter code given in the :doc:`Quick Start Guide <quick-start>`:

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


This basic driver allows for a user to query the device the driver is running on, to which the device will return the greeting stored on the disc, which is initiated as 'Hello World' on creation.
To run the driver, place the SimpleDriver.py file within the AFL/automation/instrument file and run from the command line:

.. code-block:: bash

    python -m AFL.automation.instrument.SimpleDriver

Doing so will show an output on the CLI that lists the system info, added routes, and the API server starting. With this, you can now view the server located at http://localhost:5000.

.. image:: ../images/BasicDriver-Default.png

This is the default page for the driver that can be used to view the tasks that have been queued and run through the driver which will be displayed on the right hand side as well as commands to operate on the currently running task.

With the driver running, we can now queue a task. To do so, we use a slightly modified Client.py file, also located within the :doc:`Quick Start Guide <quick-start>`:

.. code-block:: python

    from AFL.automation.APIServer.Client import Client

    # Connect to the service
    client = Client('localhost',port=5000)
    client.login(username = 'test')

    # Call a method
    response = client.enqueue(task_name='say_hello',interactive=True)
    print(response['return_val'])  # Outputs: 'Hello, World!'

    # Call a method asynchronously
    response = client.enqueue(task_name='say_hello',interactive=False)
    print(response)  # Outputs a uuid

In the above code, two separate ways of enqueuing the task say_hello are performed: one that directly returns the result of the task, and one that returns the associated UUID, determined by the interactive flag.

Running the Client.py file will result in an output of:

.. code-block:: bash
    Hello, World!
    QD-05cdd0ed-6f25-45e6-8d70-1528e9de4064

Viewing the website at http://localhost:5000 now displays that both say_hello tasks were completed:

.. image:: ../images/BasicDriver-AfterQueue.png


