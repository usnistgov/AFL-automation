=============
Driver.config
=============

The configuration system in AFL-automation is designed to provide persistent settings management that automatically saves changes to disk. This document explains how the ``Driver.config`` system works and how to use it effectively.

Core Components
--------------

The configuration system is built on two main components:

1. ``Driver.config`` - The configuration interface accessible through any Driver instance
2. ``PersistentConfig`` - The underlying dictionary-like class that handles persistence

How It Works
-----------

When a Driver instance is created, a ``PersistentConfig`` object is initialized at ``self.config``. This creates or loads a configuration file in the user's home directory at ``~/.afl/<driver_name>.config.json``. The configuration is a key-value store that behaves like a dictionary.

.. code-block:: python

    # Example of creating a Driver with configuration
    from AFL.automation.APIServer.Driver import Driver
    
    # Initialize with defaults and overrides
    driver = Driver(
        name="MyDriver",
        defaults={"setting1": "default_value"},
        overrides={"priority_setting": "override_value"}
    )

Configuration Lifecycle
----------------------

The ``PersistentConfig`` class manages the full lifecycle of configuration values:

1. **Initialization**: Loads existing config from disk if available
2. **Default Values**: Applies default values for missing keys
3. **Overrides**: Applies override values that take precedence over existing values
4. **History Tracking**: Records a history of configuration changes with timestamps
5. **Persistence**: Automatically writes changes to disk when values are modified

Configuration Methods
--------------------

The Driver class provides several methods to interact with the configuration remotely:

.. code-block:: python

    # Set configuration values
    driver.set_config(key1="value1", key2="value2")
    
    # Get a specific configuration value
    value = driver.get_config("key1")
    
    # Get a configuration value and print it to console
    value = driver.get_config("key1", print_console=True)
    
    # Get all configuration values
    config_dict = driver.get_configs()
    
    # Get all configurations and print them to console
    config_dict = driver.get_configs(print_console=True)

The underlying ``PersistentConfig`` object can also be used directly for more advanced operations:

.. code-block:: python

    # Dictionary-like access
    driver.config["key"] = "value"
    value = driver.config["key"]
    
    # Update multiple values
    driver.config.update({"key1": "value1", "key2": "value2"})
    
    # Convert to JSON
    json_data = driver.config.toJSON()
    
    # Revert to a previous configuration state
    driver.config.revert(nth=-2)  # Revert to second-most recent config

Browser-Based Configuration Editor
--------------------------------

AFL-automation provides a browser-based GUI configuration editor that makes it easy to modify configuration values with simple data types. This editor is automatically available through the web interface and provides:

1. **User-Friendly Interface**: Edit configuration values without writing code
2. **Type-Aware Inputs**: Appropriate input controls based on data type (text fields, toggles, dropdowns, etc.)
3. **Real-Time Updates**: Changes are immediately applied and persisted

The configuration editor supports these simple data types:
- Strings
- Numbers (integers and floats)
- Booleans
- Lists of simple types
- Simple dictionaries

Complex data structures (deeply nested objects, custom classes) are not editable through the GUI editor and require programmatic access.

The configuration editor can be accessed directly through the web interface at ``/config`` when running an AFL server.

Configuration History
--------------------

One powerful feature of the ``PersistentConfig`` class is its ability to track the history of configuration changes. Each time a configuration is modified, the entire configuration state is saved with a timestamp. This allows for:

1. **Auditing**: See when configuration changes were made
2. **Reverting**: Revert to previous configuration states
3. **Tracking**: Track the history of specific configuration values

.. code-block:: python

    # Get historical values for a specific key
    dates, values = driver.config.get_historical_values("key1")
    
    # Get historical values with datetime objects instead of string timestamps
    dates, values = driver.config.get_historical_values("key1", convert_to_datetime=True)

Best Practices
-------------

When working with the Driver.config system:

1. **Use Defaults**: Provide sensible defaults when creating Driver instances
2. **Documentation**: Document the configuration keys your Driver expects
3. **Validation**: Validate configuration values before using them
4. **Error Handling**: Handle missing configuration gracefully
5. **Keep It Simple**: Avoid deeply nested configuration structures

Examples
--------

Here's a complete example of using the Driver.config system:

.. code-block:: python

    from AFL.automation.APIServer.Driver import Driver
    
    # Create a Driver with default configuration
    defaults = {
        "serial_port": "/dev/ttyUSB0",
        "baud_rate": 9600,
        "timeout": 1.0
    }
    
    driver = Driver("DeviceController", defaults=defaults)
    
    # Override a configuration value
    driver.set_config(timeout=2.0)
    
    # Use configuration in methods
    def connect_to_device(self):
        port = self.get_config("serial_port")
        baud = self.get_config("baud_rate")
        timeout = self.get_config("timeout")
        # Connect using these parameters...

Conclusion
----------

The Driver.config system provides a robust way to manage persistent configuration in AFL-automation. By leveraging the ``PersistentConfig`` class, it offers a simple dictionary-like interface with powerful features like history tracking and automatic persistence to disk.
