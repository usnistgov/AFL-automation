.. AFL-automation documentation master file, created by
   sphinx-quickstart on Tue May 28 13:58:39 2024.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

AFL-automation: Instrument Control Framework
=============================================

AFL-automation is a framework for instrument control and laboratory automation. It powers the NIST AFL (Autonomous Formulation Laboratory), but is designed to be versatile for many scientific instrumentation needs. It enables the easy conversion of Python classes - drivers - into robust HTTP microservices with authentication, task queueing, UI generation, data management, and more.

Documentation Structure
------------------------

This documentation is organized according to the philosphy described by Daniele Procida at `diataxis.fr <https://diataxis.fr>`_. It is organized into four sections:

* :doc:`Tutorials <tutorials/index>`: Step-by-step guides for beginners
* :doc:`How-to <how-to/index>`: Guides for specific tasks
* :doc:`Explanations <explanation/index>`: Discussions of underlying principles and concepts
* :doc:`Reference <reference/index>`: Detailed technical reference 

Table of Contents
------------------
.. toctree::
   :maxdepth: 2

   tutorials/installation
   tutorials/index
   how-to/index
   explanation/index
   reference/index
   modules
