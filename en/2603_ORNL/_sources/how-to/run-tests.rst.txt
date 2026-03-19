=====================
Running the Test Suite
=====================

The project uses `pytest` for its unit tests. Continuous integration on GitHub
Actions executes these tests automatically for every push and pull request via
the :file:`.github/workflows/test.yaml` workflow. This workflow installs the
package and its dependencies as declared in :file:`pyproject.toml`.

To run the tests locally, first install the package in editable mode and then
invoke `pytest`. If the installation fails because the package version cannot be
determined from Git tags, set ``SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0``:

.. code-block:: bash

   SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 pip install -e .
   pytest

