======================
Using GNU Screen 
======================

GNU Screen is a platform that manages multiple terminal sessions in a single window. It allows users to handle starting/detaching processes, multiple windows, and session sharing as well as serves as a way for the server to run in the background so users and view and interact with it.

Installation
----------------
To install GNU Screen, you can use your system's package manager.

- For Debian/Ubuntu:
  
  .. code-block:: bash
        sudo apt-get install screen

- For macOS (using Homebrew):
    
    .. code-block:: bash
        brew install screen

- For Windows, you can use a terminal emulator like Git Bash or WSL (Windows Subsystem for Linux) to access GNU Screen.

Basic Commands
----------------
- Start a new screen session:
  
  .. code-block:: bash
        screen 

- Start a new session with a name (easier to find later):
    
    .. code-block:: bash
        screen -S session_name

- Detach from the current session (leaves it running in the background):
  
  .. code-block:: bash
        Ctrl + A, then D

- List all screen sessions:
    
    .. code-block:: bash
        screen -ls

- Reattach to a session:
    
    .. code-block:: bash
        screen -r session_name

- Kill a session:
   
    .. code-block:: bash
        screen -X -S session_name quit

AFL Use
----------------
When running AFL-automation on a server, you can start a screen session to run the server in the background. This allows you to keep the server running even if you disconnect from the terminal.

When using AFL-automation, it is important to use screen to manage your server sessions effectively and allow the API server to run in the background while you work on other tasks or disconnect from the terminal.

Certain repos like _____ require screen to run the server in the background, so it is important to understand how to use it effectively.

Additional Resources
----------------------
- GNU Screen Manual: https://www.gnu.org/software/screen/manual/screen.html 


