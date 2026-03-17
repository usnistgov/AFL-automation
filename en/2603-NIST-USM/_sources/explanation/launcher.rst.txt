=========================
AFL-automation Launching System
=========================

Configuration as Configuration, Not Code
--------------------------

The AFL-automation framework uses a powerful launching system that allows experimental setups to be defined through configuration rather than code changes. This document explains how the launcher works and how to customize it for your specific needs.

Overview
--------

The launcher system is responsible for:

* Discovering and loading appropriate driver modules
* Managing persistent configuration across sessions
* Reconstituting complex Python objects from configuration files
* Starting the APIServer with appropriate settings
* Supporting both interactive and non-interactive operation modes

Core Components
--------------

Persistent Configuration
^^^^^^^^^^^^^^^^^^^^^^^

At the heart of the launcher is the ``PersistentConfig`` system. This maintains a systemwide configuration file at ``~/.afl/config.json`` which stores important settings such as:

* Owner email address (for notifications)
* System serial number
* Tiled server connection details
* Network binding configuration
* Driver-specific port assignments
* Custom driver configurations

This persistent storage ensures that your experimental setup remains consistent across restarts, while maintaining a history of previous configurations.

Driver Discovery
^^^^^^^^^^^^^^^

The launcher automatically discovers which driver module to use by examining the main Python module being executed. It does this by:

1. Looking for an optional ``_OVERRIDE_MAIN_MODULE_NAME`` attribute
2. Falling back to the name of the main script file being executed
3. Finding the appropriate driver class within that module

This design allows multiple driver scripts to share the same launcher code without modification.

Object Reconstitution
^^^^^^^^^^^^^^^^^^^^

One of the most powerful features of the launcher is its ability to recreate complex Python objects from simple JSON configuration. This "reconstitution" process supports:

* Creating objects with both positional and keyword arguments
* Building nested object hierarchies
* Automatic dependency injection (such as data handlers)
* Lists and other collection types

This allows experimental configurations to be stored as human-readable JSON rather than code.

Example Configuration
-------------------

A driver's custom configuration might look like this in the configuration file::

    'PneumaticPressureLoader': {
        '_classname': 'AFL.automation.loading.PneumaticPressureLoader.PneumaticPressureLoader',
        'p_ctrl': { 
            '_classname': 'AFL.automation.loading.DigitalOutPressureController.DigitalOutPressureController',
            'dig_out': {
                '_classname': 'AFL.automation.loading.LabJackDigitalOut',
                'port': 'DIO1'
            }
        }
    }

This configuration would automatically create a ``PneumaticPressureLoader`` with its associated controllers and I/O devices.

Usage Modes
----------

The launcher supports two primary modes of operation:

Non-interactive Mode
^^^^^^^^^^^^^^^^^^^^

By default, the launcher starts the APIServer and blocks until shutdown::

    python my_driver.py

or, for a production deployment of existing code:

    python -m AFL.automation.loading.PneumaticPressureLoader

This is ideal for production deployments where the server runs continuously.

Interactive Mode
^^^^^^^^^^^^^^^

By passing the ``-i`` or ``--interactive`` flag, the launcher starts the APIServer in a background thread and drops into an interactive Python shell::

    python my_driver.py -i

This is extremely useful for development, debugging, and manual experimentation, as it provides direct access to the driver and server objects.
It is important to say, however, that this is a ~dangerous~ mode to run in - you can directly alter the memory of the running server.  Be careful.

Customizing Your Driver
---------------------

Default Port Assignment
^^^^^^^^^^^^^^^^^^^^^^

You can specify a default port for your driver by adding a ``_DEFAULT_PORT`` attribute to your driver module::

    # In my_driver.py
    _DEFAULT_PORT = 5001

Default Custom Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Similarly, you can provide a default custom configuration by adding a ``_DEFAULT_CUSTOM_CONFIG`` attribute::

    # In my_driver.py
    _DEFAULT_CUSTOM_CONFIG = {
        '_classname': 'path.to.YourDriverClass',
        'param1': 'value1',
        'param2': 42
    }

The first time your driver runs, this configuration will be saved to the persistent configuration file.

Startup Flow
-----------

When a driver is launched, the following sequence occurs:

1. The launcher identifies the appropriate driver module and class
2. Persistent configuration is loaded from ``~/.afl/config.json``
3. Default configurations are applied if missing from the persistent store
4. Environment variables are set (e.g., ``AFL_SYSTEM_SERIAL``)
5. If a Tiled server is configured, a data connection is established
6. Driver objects are reconstituted from configuration
7. The APIServer is created and configured
8. Standard routes and command queue are set up
9. The server starts in either interactive or non-interactive mode

Troubleshooting
--------------

If you encounter issues with the launcher:

* Check that your driver module follows naming conventions (module name matches class name)
* Verify that the ``~/.afl/config.json`` file exists and contains valid JSON
* Ensure all required Python modules can be imported
* Look for error messages about missing configuration entries

For persistent issues, you can manually edit the configuration file or remove it to reset to defaults.
