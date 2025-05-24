"""
This module contains functions to exclude specific modules from autodoc generation.
"""

def skip_nbutil(app, what, name, obj, would_skip, options):
    """
    Skip nbutil-related modules from being documented.
    This is connected to the autodoc-skip-member event to prevent
    nbutil scripts from appearing in the documentation.
    """
    # Check for module name or object name containing nbutil
    if 'nbutil' in name:
        print(f"Skipping documentation for {name}")
        return True
    
    # Skip by full module path
    modules_to_skip = [
        'AFL.automation.shared.nbutil',
        'nbutil',
        'AFL.automation.shared.nbutil-APS',
        'AFL.automation.shared.nbutil-CHESS',
        'AFL.automation.shared.nbutil-SINQ'
    ]
    
    # Skip modules or objects from these modules
    for mod in modules_to_skip:
        if name.startswith(mod) or mod in name:
            print(f"Skipping documentation for {name} (matched {mod})")
            return True
    
    # Check the module of the object
    if hasattr(obj, '__module__') and obj.__module__:
        if 'nbutil' in obj.__module__:
            print(f"Skipping documentation for {name} (in module {obj.__module__})")
            return True
    
    return would_skip

def setup(app):
    """
    Connect the skip function to the autodoc-skip-member event.
    """
    app.connect('autodoc-skip-member', skip_nbutil)
