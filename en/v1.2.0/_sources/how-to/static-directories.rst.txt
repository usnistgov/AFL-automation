===========================
Serving Static Files in Drivers
===========================

AFL-automation drivers can serve static files (HTML, CSS, JavaScript, images, etc.) through the API server's web interface. This is useful for providing custom web interfaces, documentation, or any files that need to be accessible via HTTP.

How It Works
-----------

When you define static directories in your driver class, the API server automatically creates HTTP routes to serve files from those directories. Files are served under the `/static/` URL path.

Basic Usage
----------

To serve static files from your driver, define a class-level `static_dirs` dictionary that maps URL subpaths to filesystem directories:

.. code-block:: python

    from AFL.automation.APIServer.Driver import Driver
    import pathlib

    class MyDriver(Driver):
        # Map URL subpaths to filesystem directories
        static_dirs = {
            'docs': '/path/to/my/documentation',
            'assets': '/path/to/web/assets',
            'data': pathlib.Path(__file__).parent / 'static_data'
        }

        def __init__(self, name="MyDriver"):
            super().__init__(name)
            # static_dirs are automatically collected and configured

With this configuration:

- Files in `/path/to/my/documentation/` are served at `http://server:port/static/docs/filename`
- Files in `/path/to/web/assets/` are served at `http://server:port/static/assets/filename`  
- Files in `static_data/` directory are served at `http://server:port/static/data/filename`

Inheritance
----------

Static directories are inherited from parent classes and combined using the Method Resolution Order (MRO). This allows for modular composition of static assets:

.. code-block:: python

    class BaseDriver(Driver):
        static_dirs = {
            'common': '/shared/assets',
            'docs': '/base/documentation'
        }

    class SpecializedDriver(BaseDriver):
        static_dirs = {
            'custom': '/specialized/assets',
            'docs': '/specialized/documentation'  # Overrides base docs
        }

    # SpecializedDriver will serve:
    # /static/common/ -> /shared/assets
    # /static/custom/ -> /specialized/assets  
    # /static/docs/ -> /specialized/documentation (overridden)

Example: Custom Web Interface
----------------------------

Here's a complete example of a driver that serves a custom web interface:

.. code-block:: python

    import pathlib
    from AFL.automation.APIServer.Driver import Driver

    class DataVisualizationDriver(Driver):
        # Serve web interface files
        static_dirs = {
            'viewer': pathlib.Path(__file__).parent / 'web_interface',
            'plots': pathlib.Path(__file__).parent / 'generated_plots'
        }

        def __init__(self, name="DataViz"):
            super().__init__(name)

        @queued(render_hint='html')
        def view_dashboard(self):
            """Return HTML that loads the custom web interface"""
            return '''
            <iframe src="/static/viewer/dashboard.html" 
                    width="100%" height="600px">
            </iframe>
            '''

Directory Structure
-----------------

For the above example, your directory structure might look like:

::

    my_driver/
    ├── driver.py                    # Your driver class
    ├── web_interface/              # static_dirs['viewer']
    │   ├── dashboard.html
    │   ├── style.css
    │   ├── app.js
    │   └── lib/
    │       └── charts.js
    └── generated_plots/            # static_dirs['plots']
        ├── plot1.png
        └── plot2.svg

Files would be accessible at:

- `http://server:port/static/viewer/dashboard.html`
- `http://server:port/static/viewer/style.css`
- `http://server:port/static/viewer/lib/charts.js`
- `http://server:port/static/plots/plot1.png`

Security Considerations
---------------------

- Only files within the specified directories are served
- Directory traversal attacks (e.g., `../../../etc/passwd`) are prevented by Flask's `send_from_directory` function
- Consider the sensitivity of files you're serving - they'll be publicly accessible if the server is accessible
- Use appropriate file permissions on the directories you're serving

Best Practices
-------------

1. **Use relative paths**: Use `pathlib.Path(__file__).parent` to make paths relative to your driver file
2. **Organize logically**: Group related files under meaningful subpath names
3. **Version control**: Include static assets in your driver's version control
4. **Documentation**: Document what static endpoints your driver provides
5. **Testing**: Test that your static files are served correctly after server startup

Troubleshooting
--------------

**Files not being served**

- Verify the directory exists and contains files
- Check file permissions are readable by the server process
- Confirm the `static_dirs` dictionary is defined at the class level
- Check server logs for any error messages

**Wrong files being served**

- Check for inheritance conflicts if using multiple driver classes
- Verify the correct directory paths in `static_dirs`
- Remember that child classes override parent class mappings for the same subpath 