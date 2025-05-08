.. AFL-automation documentation master file, created by
   sphinx-quickstart on Tue May 28 13:58:39 2024.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

AFL-automation: Instrument Control Framework
===========================================

AFL-automation is a framework for instrument control and laboratory automation. It powers the NIST AFL (Autonomous Formulation Laboratory), but is designed to be versatile for many scientific instrumentation needs. It enables the easy conversion of Python classes - drivers - into robust HTTP microservices with authentication, task queueing, UI generation, data management, and more.

.. toctree::
   :maxdepth: 1
   :caption: Getting Started
   
   tutorials/installation
   tutorials/quick-start

.. toctree::
   :maxdepth: 1
   :caption: Tutorials
   
   tutorials/index

.. toctree::
   :maxdepth: 1
   :caption: How-to Guides
   
   how-to/index
   how-to/dependencies

.. toctree::
   :maxdepth: 1
   :caption: Explanation
   
   explanation/index
   explanation/architecture

.. toctree::
   :maxdepth: 1
   :caption: Reference
   
   reference/index
   api
   modules


Module Documentation
===================

.. autosummary::
   :toctree: _autosummary
   :template: custom-module-template.rst
   :recursive:

   AFL.automation
   AFL.automation.APIServer
   AFL.automation.instrument
   AFL.automation.loading
   AFL.automation.prepare
   AFL.automation.sample
   AFL.automation.sample_env
   AFL.automation.shared

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
