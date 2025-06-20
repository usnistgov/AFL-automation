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
copyright = ': Contribution of the US Government.  Not subject to copyright in the United States.'
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
    "sphinx.ext.coverage",
    "sphinx_copybutton",
    "nbsphinx",
	]
nbsphinx_requirejs_path = "_static/require.min.js"

# Ignore annoying type exception warnings which often come from newlines
nitpick_ignore = [("py:class", "type")]


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
    'AFL.automation.shared.launcher',
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

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
import os
from importlib import import_module

html_theme = "pydata_sphinx_theme"
theme_module = import_module(html_theme.replace("-", "_"))
html_theme_path = [os.path.dirname(os.path.abspath(theme_module.__file__))]

# Add the favicon
html_favicon = "_static/logo_light.svg"

# Add the logo to replace the title text
html_logo = "_static/logo_text_large_light.svg"

html_theme_options = {
    "github_url": "https://github.com/usnistgov/AFL-automation",
    "collapse_navigation": True,
    "header_links_before_dropdown": 6,
    "navbar_end": ["theme-switcher", "navbar-icon-links"],
    "logo": {
        "image_light": "_static/logo_text_large_light.svg",
        "image_dark": "_static/logo_text_large_dark.svg",
    },
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]


# Copy the iframe_figures directories to the build output
# This is a workaround to allow the iframe_figures from plotly 
# to be displayed in the build output
def copy_iframe_figures_dirs(app, exception):
    """
    After the build, walk through the source directory, find all directories
    named "iframe_figures", and copy them (with their contents) to the corresponding
    location in the build output.
    """
    if exception is not None:
        return

    src_root = app.srcdir
    out_dir = app.builder.outdir

    # Walk through the source directory.
    for root, dirs, _ in os.walk(src_root):
        for dirname in dirs:
            if dirname == "iframe_figures":
                # Full path to the found iframe_figures directory in the source.
                src_iframe_dir = os.path.join(root, dirname)
                # Determine relative path from the source root.
                rel_path = os.path.relpath(src_iframe_dir, src_root)
                # Determine the target path in the build directory.
                target_dir = os.path.join(out_dir, rel_path)

                # If a directory already exists at the target, remove it.
                if os.path.exists(target_dir):
                    shutil.rmtree(target_dir)

                # Now copy the entire directory tree.
                shutil.copytree(src_iframe_dir, target_dir)

def setup(app):
    app.connect("build-finished", copy_iframe_figures_dirs)

