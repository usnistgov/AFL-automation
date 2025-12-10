=========================
AFL-automation Architecture
=========================

This page explains the core architecture of AFL-automation and how its components work together.

Core Concepts
------------

AFL-automation is built around several key concepts:

1. **Drivers**: Python classes that interface with hardware or provide services
2. **APIServer**: A Flask-based web server that exposes drivers via HTTP
3. **Task Queue**: A system for managing asynchronous tasks
4. **Client**: A Python client for interacting with remote services

Architecture Diagram
------------------

The following diagram illustrates the high-level architecture:

::

    +----------------+      +-----------------+      +----------------+
    |                |      |                 |      |                |
    |  Driver Class  +----->+  API Server     +<---->+  Client        |
    |  (Hardware)    |      |  (Flask)        |      |  (Python/HTTP) |
    |                |      |                 |      |                |
    +----------------+      +-----------------+      +----------------+
                                    ^
                                    |
                                    v
                            +-----------------+
                            |                 |
                            |  Task Queue     |
                            |  (Background)   |
                            |                 |
                            +-----------------+

Driver System
-----------

The driver system is the core of AFL-automation. Drivers:

- Encapsulate hardware control logic
- Define configuration parameters with defaults
- Provide methods for interacting with hardware
- Support lazy loading of hardware-specific dependencies
- Can serve static files for custom web interfaces via `static_dirs`

API Server
---------

The API server:

- Exposes driver methods via HTTP endpoints
- Provides authentication and authorization
- Manages a task queue for asynchronous operations
- Offers a web UI for monitoring and control
- Serves static files defined by drivers for custom web interfaces

Dependency Management
-------------------

AFL-automation uses a modular dependency system:

- Core dependencies are always installed
- Hardware-specific dependencies are optional
- Lazy loading ensures code works even without all dependencies
- The extras system makes installation straightforward

For details on managing dependencies, see :doc:`/how-to/dependencies`.
