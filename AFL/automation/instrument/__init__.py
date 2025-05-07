import pathlib

if (pathlib.Path.home()/'nicos').exists():
    # we need to add nicos to the PYTHONPATH, due to SGSE
    print('Presumably uninstallable nicos directory found, patching into PYTHONPATH')
    import sys
    sys.path.insert(0,f'/home/afl642/nicos')

