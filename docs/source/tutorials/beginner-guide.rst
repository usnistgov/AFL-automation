Beginner Guide
=====

This tutorial will guide you through basic examples of using the AFL through use of a raspberry pi. After going through this tutorial, you will learn:

- How to queue basic commands to the AFL and view the results
- How to queue hardware specific commands to the AFL and view the results
- How to set up external devices to be used with the AFL

Prerequisites
-----------------

To fully utilize this tutorial, a raspberry pi with internet access and the AFL installed is required. For how to install the AFL, please see the :doc:`Quick Start Guide <quick-start>`

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
