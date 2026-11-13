Setup
=====

This tutorial will guide you through the process of installing AFL-automation and its dependencies.

Basic Installation
-----------------

AFL-automation can be installed using pip:

.. code-block:: bash

    pip install AFL-automation

This will install the core dependencies needed for basic functionality.

Installation with Hardware Support
---------------------------------

Depending on your specific hardware needs, you may want to install additional dependencies:

.. code-block:: bash

    # For Ocean Insight spectrometers
    pip install AFL-automation[seabreeze]
    
    # For Opentrons liquid handling robots
    pip install AFL-automation[opentrons]
    
    # For multiple hardware types
    pip install AFL-automation[seabreeze,opentrons]

For a complete list of available extras and what they provide, see the :doc:`/how-to/dependencies` page.

Development Installation
-----------------------

For development, you might want to install in editable mode with additional tools:

.. code-block:: bash

    git clone https://github.com/usnistgov/AFL-automation.git
    cd AFL-automation
    pip install -e .
    
    # Install development tools
    pip install -e ".[docs]"
