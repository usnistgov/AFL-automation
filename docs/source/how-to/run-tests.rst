=====================
Running the Test Suite
=====================

The project uses `pytest` for its unit tests. Continuous integration on GitHub Actions
executes these tests automatically for every push and pull request via the
:file:`.github/workflows/test.yaml` workflow.

To run the tests locally, first install the package in editable mode with its
core dependencies and then invoke `pytest`:

.. code-block:: bash

   pip install -e .
   pytest

