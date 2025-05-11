# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
sys.path.insert(0, os.path.abspath('../..'))  # Source code dir relative to this file
sys.path.insert(0, os.path.abspath('.'))  # Add current directory to path

# Import custom autodoc skip module
import autodoc_skip


project = 'AFL-automation'
copyright = 'Contribution of the US Government.  Not subject to copyright in the United States.'
author = 'NIST AFL Team'



# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
	'sphinx.ext.duration',
	'sphinx.ext.doctest',
	'sphinx.ext.autodoc',
	'sphinx.ext.autosummary',
	'sphinx.ext.viewcode',
	'sphinx.ext.napoleon',
	'sphinx.ext.intersphinx',
	]

templates_path = ['_templates']
# Exclude script files from documentation
exclude_patterns = ['**/nbutil*.py', '**/nbutil-*.py']

# Autosummary settings
autosummary_generate = True
autosummary_imported_members = True
# Explicitly exclude nbutil modules from documentation
# Mock imports for dependencies that may not be available during documentation generation
autosummary_mock_imports = [
    # Notebook utility modules
    "AFL.automation.shared.nbutil", "AFL.automation.shared.nbutil-APS",
    "AFL.automation.shared.nbutil-CHESS", "AFL.automation.shared.nbutil-SINQ",
    
    # Exclude launcher because it will try to launch sphinx-build, lol
    'AFL.automation.shared.launcher'
    # NICE and nicos-related modules
    "nice", "nice.api.console.ConsoleMonitor", "nice.api.data.DataMonitor", "nice.api.devices.DevicesMonitor",
    "nicos", "nicos.clients.base", "nicos.clients.base.NicosClient", "nicos.clients.base.ConnectionData",
    "nicos.utils.loggers", "nicos.utils.loggers.ACTION", "nicos.utils.loggers.INPUT",
    "nicos.protocols.daemon", "nicos.protocols.daemon.BREAK_AFTER_LINE", 
    "nicos.protocols.daemon.BREAK_AFTER_STEP", "nicos.protocols.daemon.STATUS_IDLE", 
    "nicos.protocols.daemon.STATUS_IDLEEXC",
    ]
modparse_mock_imports = autosummary_mock_imports

# Napoleon settings
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_type_aliases = None

# Autodoc settings
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__'
}

# Explicitly exclude nbutil modules from autodoc
modules_to_exclude = [
    'AFL.automation.shared.nbutil',
    'AFL.automation.shared.nbutil-APS',
    'AFL.automation.shared.nbutil-CHESS',
    'AFL.automation.shared.nbutil-SINQ',
]

# Create a custom handler to skip certain modules during autodoc
def skip_modules_handler(app, what, name, obj, skip, options):
    if any(name.startswith(module) for module in modules_to_exclude):
        return True
    return None

def setup(app):
    app.connect('autodoc-skip-member', skip_modules_handler)

# Intersphinx mapping
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'pandas': ('https://pandas.pydata.org/docs/', None),
    'scipy': ('https://docs.scipy.org/doc/scipy/', None),
    'matplotlib': ('https://matplotlib.org/stable/', None),
}


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_title = 'AFL-automation Documentation'
html_logo = None  # Add a logo path here if you have one
html_favicon = None  # Add a favicon path if you have one

# Theme options
html_theme_options = {
    'navigation_depth': 4,
    'collapse_navigation': False,
    'sticky_navigation': True,
    'includehidden': True,
    'titles_only': False,
    'display_version': True,
}
