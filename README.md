NIST Autonomous Formulation Laboratory - Automation Software

This package contains the core laboratory automation software used in the NIST AFL platform.

Its core is the 'DeviceServer' API, a simple way of exposing functionality in simple Python classes to the outside world via HTTP servers.  It includes robust item queueing support, output rendering, and hooks to allow for 'smart' generation of user interfaces automatically.

Specific deviceserver instances are provided for a variety of hardware used in the AFL platform: syringe pumps, valves, multiposition flow selectors, UV-Vis spectrometers, x-ray and neutron scattering instruments/beamlines.  There are further deviceserver classes that integrate these base devices to perform higher-level functions, e.g. "loading".  These classes aim to specify instructions for running a particular protocol in a hardware-agnostic way.


## Virtual servers for offline testing

Several stub modules are provided so you can launch the AFL stack without any physical hardware. Running one of these modules the first time creates `~/.afl/config.json` containing the Tiled server URL, API key and port bindings. Update this file as needed.

Example commands to start the dummy services:

```bash
# start a dummy OT2 robot
python -m AFL.automation.prepare.Dummy_OT2_Driver

# start a virtual sample loader
python server_scripts/virtual_instrument/DummyLoader.py

# optional virtual detectors
python server_scripts/virtual_instrument/VirtualSANS_data.py
python server_scripts/virtual_instrument/VirtualSpec_Data.py
```

For a full offline demo you can start everything at once:

```bash
python server_scripts/virtual_instrument/AllDummy.py
```

These stub servers expose the same HTTP API as the real hardware allowing you to test an AFL workflow entirely in software.
