NIST Autonomous Formulation Laboratory - Automation Software

This package contains the core laboratory automation software used in the NIST AFL platform.

Its core is the 'DeviceServer' API, a simple way of exposing functionality in simple Python classes to the outside world via HTTP servers.  It includes robust item queueing support, output rendering, and hooks to allow for 'smart' generation of user interfaces automatically.

Specific deviceserver instances are provided for a variety of hardware used in the AFL platform: syringe pumps, valves, multiposition flow selectors, UV-Vis spectrometers, x-ray and neutron scattering instruments/beamlines.  There are further deviceserver classes that integrate these base devices to perform higher-level functions, e.g. "loading".  These classes aim to specify instructions for running a particular protocol in a hardware-agnostic way.


### Production deployment
By default the APIServer will use the [waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/) WSGI server if it is installed. To fall back to Flask's built-in server pass `--no-waitress` to `AFL.automation.shared.launcher`.

### Running tests
This repository uses `pytest` for unit tests. A GitHub Actions workflow runs the tests automatically on every push and pull request using `.github/workflows/test.yaml`.

To execute the tests locally, install the package in editable mode with its dependencies and run `pytest`:

```bash
pip install -e .
pytest
```
