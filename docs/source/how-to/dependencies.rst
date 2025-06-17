======================
Managing Dependencies
======================

The AFL-automation package uses a modular dependency system to handle various hardware and specialized libraries. This allows you to install only the dependencies you need for your specific hardware configuration.

Core Dependencies
----------------

The core dependencies are installed automatically when you install the package. These include:

- **Web framework components**: Flask, Flask-CORS, Flask-JWT-Extended
- **Data processing libraries**: NumPy, pandas, SciPy, xarray, h5py
- **Visualization tools**: Matplotlib, Plotly, Bokeh, ipywidgets
- **Scientific utilities**: periodictable, scikit-learn, scikit-image

Optional Dependencies (Extras)
-----------------------------

The package uses Python's "extras" mechanism to manage optional dependencies. You can install these using pip:

.. code-block:: bash

    # Install with specific hardware support
    pip install AFL-automation[seabreeze,opentrons]
    
    # Install with scattering support
    pip install AFL-automation[scattering-processing,sas-analysis]

Available Extras
---------------

Hardware Interfaces
^^^^^^^^^^^^^^^^^^

.. list-table::
   :widths: 20 30 50
   :header-rows: 1

   * - Extra Name
     - Package(s)
     - Description
   * - ``labjack``
     - labjack-ljm
     - Support for LabJack data acquisition hardware
   * - ``piplates``
     - piplates
     - Support for Pi-Plates hardware add-ons
   * - ``rpi-gpio``
     - RPi.GPIO
     - Raspberry Pi GPIO interface libraries
   * - ``serial``
     - pyserial
     - Serial communication support for instruments
   * - ``seabreeze``
     - seabreeze
     - Support for Ocean Optics/Ocean Insight spectrometers
   * - ``opentrons``
     - opentrons
     - Support for Opentrons liquid handling robots
   * - ``pyspec``
     - certif-pyspec
     - Support for CHESS and other beamline control
   * - ``remote-access``
     - paramiko
     - SSH client for remote instrument connections

Scientific Processing
^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :widths: 20 30 50
   :header-rows: 1

   * - Extra Name
     - Package(s)
     - Description
   * - ``scattering-processing``
     - fabio, pyFAI
     - Scattering data processing and azimuthal integration
   * - ``sas-analysis``
     - sasmodels, sasdata
     - Small-Angle Scattering analysis tools
   * - ``ml``
     - tensorflow, gpflow
     - Machine learning utilities for data analysis
   * - ``geometry``
     - alphashape, shapely
     - Geometric analysis and manipulation tools

Neutron Scattering
^^^^^^^^^^^^^^^^^

.. list-table::
   :widths: 20 30 50
   :header-rows: 1

   * - Extra Name
     - Package(s)
     - Description
   * - ``neutron-scattering``
     - epics, sans, mantid
     - Support for neutron scattering instrumentation
   * - ``nice-neutron-scattering``
     - nice
     - NIST NCNR NICE control system

Documentation
^^^^^^^^^^^^

.. list-table::
   :widths: 20 30 50
   :header-rows: 1

   * - Extra Name
     - Package(s)
     - Description
   * - ``docs``
     - sphinx, sphinx-rtd-theme, sphinx-autodoc-typehints, sphinx-copybutton, myst-parser, nbsphinx
     - Tools for building documentation

Implementation Details
---------------------

AFL-automation uses lazy loading for optional dependencies. This means that:

1. You can import the package without having all optional dependencies installed
2. Dependencies are only loaded when actually used (via the ``lazy_loader`` library)
3. Clear error messages will tell you which extra to install if you try to use a feature without its required dependency

Example of error when trying to use a feature without the required dependency:

.. code-block:: python

    >>> from AFL.automation.instrument import SeabreezeUVVis
    >>> spectrometer = SeabreezeUVVis()
    ImportError: This module requires the 'seabreeze' package. 
    Please install it: pip install AFL-automation[seabreeze]

Importing Multiple Hardware Packages
-----------------------------------

If you need support for multiple hardware types, you can specify multiple extras:

.. code-block:: bash

    pip install AFL-automation[seabreeze,opentrons,scattering-processing]

Core packages that are not tied to specific hardware will be loaded normally without any special handling.
