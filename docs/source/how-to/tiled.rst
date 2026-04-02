======================
Using Tiled Server
======================

Tiled is a Python-based data server developed by Bluesky/NSLS-II that serves structured scientific data (arrays, dataframes, etc) via HTTP. It is designed to hlep scientists store, access, and find scientific data at scall and supports parallel uploads and downloads for efficient transfers. 

Installation
----------------
To install Tiled Server, you can use pip:

.. code-block:: bash

    pip install tiled


Setting up Tiled Server
----------------
To set up Tiled Server, you need to access the configuration file (AFL-automation/tiled/config.yml) that specifies the data sources and other settings. 

**CORS**: Cross-Origin Resource Sharing (CORS) is a browser security rule that blocks web pages from making requests to a different domain or port than the one they were loaded from. Since AFL's frontend runs on a different port than Tiled (port 5000 vs. port 8000), you need to explicitly tell Tiled which origins are allowed to talk to it, otherwise the browser will block the connection. 

Without configuring the orgin, you can still connect to the database, and the Tiled will route traffic through a same-origin proxy (shown below)

This is not an error, but it means Tiled is proxying the connection rather than serving it directly, which can affect API key handling and performance. 

.. image:: /docs/source/images/same-origin-proxy.png
   :alt: Tiled Proxy


In the terminal, run the command below to generate the API key:

.. code-block:: bash

    openssl rand -hex 32

In the tiled/config.yml file, add the generated API key under the authentication section:

.. code-block:: yml
    
    authentication:
        single_user_api_key: [your_api_key_here]

Make sure in tiled/config.yml, the following is there:

.. code-block:: yml
    
    allow_origins:
        - http://localhost:5000

Starting the Server
-----------------
Before running the Driver file, add the following to ~/.afl/config.json:

.. code-block:: json

    "tiled": {
        "url": "http://localhost:8000",
        "api_key": "your_api_key_here"
    }

**Note**: the api_key in the json file should macth the one in the tiled/config.yml file

Run the Driver file to start the API Server 

A successful startup will show a confirmation message or accessible URL within the APIServer

Database Browser
------------------

.. image:: /docs/source/images/tiled_browser.png
   :alt: Tiled Browser 

Once the API Server is running, you can access AFL's tiled database browser (typically at http://localhost:5000/tiled_browser)

This interface allows users to display AFL data as browsable nodes and datasets directly in the browser, making it easier to explore and understand the data structure.

Additional Resources
----------------------
- Tiled Server Documentation: https://blueskyproject.io/tiled/index.html  