import pathlib

if (pathlib.Path.home()/'nicos').exists():
    # we need to add nicos to the PYTHONPATH, due to SGSE
    print('Presumably uninstallable nicos directory found, patching into PYTHONPATH')
    import sys
    sys.path.insert(0,f'/home/afl642/nicos')

import importlib, sys

# Deprecated module aliases for backward compatibility
_deprecated_modules = {
    'APSDNDCAT': 'apsdndcat',
    'APSUSAXS': 'apsusaxs',
    'CDSAXSLabview': 'cdsaxslabview',
    'CHESSID3B': 'chessid3b',
    'DummySAS': 'dummy_sas',
    'FileCamera': 'file_camera',
    'GPInterpolator': 'gp_interpolator',
    'I22SAXS': 'i22saxs',
    'ISISLARMOR': 'isislarmor',
    'NICEConsole': 'nice_console',
    'NICEData': 'nice_data',
    'NICEDevice': 'nice_device',
    'NetworkCamera': 'network_camera',
    'NicosScriptClient': 'nicos_script_client',
    'OpticalTurbidity': 'optical_turbidity',
    'PySpecClient': 'py_spec_client',
    'SINQSANS': 'sinqsans',
    'SINQSANS_NICOS': 'sinqsans_nicos',
    'ScatteringInstrument': 'scattering_instrument',
    'SeabreezeUVVis': 'seabreeze_uvvis',
    'SpecScreen_Driver': 'spec_screen_driver',
    'USBCamera': 'usb_camera',
    'VirtualSANS_data': 'virtual_sans_data',
    'VirtualSAS_theory': 'virtual_sas_theory',
    'VirtualSpec_data': 'virtual_spec_data',
    'scatteringInterpolator': 'scattering_interpolator',
}
for old, new in _deprecated_modules.items():
    sys.modules[f'{__name__}.{old}'] = importlib.import_module(f'{__name__}.{new}')
