# Notes for Codex agents

This repository implements a Flask-based automation platform. The two most
important pieces are the `Driver` and the `APIServer` classes located in
`AFL/automation/APIServer/`.

## Driver
- Found in `AFL/automation/APIServer/Driver.py`.
- Base class for device-specific drivers. Subclasses expose methods that can be
  called via the API.
- Uses decorators `Driver.queued` and `Driver.unqueued` to mark methods for
  asynchronous queue execution or immediate execution.
- Manages a `PersistentConfig` object for storing configuration options.
- Provides helper methods like `execute`, `set_sample`, `deposit_obj`, and
  `retrieve_obj` that are used by the server.

## APIServer
- Found in `AFL/automation/APIServer/APIServer.py`.
- Wraps a Flask app that exposes driver functionality via HTTP endpoints.
- Maintains a task queue processed by `QueueDaemon` to run queued driver methods.
- Routes include `/enqueue` for queued tasks and `/query_driver` for unqueued
  operations, among many others.
- The server optionally advertises itself via zeroconf and can run using
  waitress or Flask's built-in server.

## Useful pointers
- The `Client` class (`AFL/automation/APIServer/Client.py`) provides a Python
  interface to interact with the server.
- Test helpers live in `test/` and may rely on optional dependencies listed in
  `requirements-basic.txt`.
- Documentation for getting started can be found in `docs/source/tutorials/quick-start.rst`
  and `docs/source/explanation/architecture.rst`.

