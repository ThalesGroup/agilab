.. image:: https://img.shields.io/pypi/v/agilab.svg?color=informational
   :target: https://pypi.org/project/agilab
.. image:: https://img.shields.io/pypi/pyversions/agilab.svg
   :target: https://pypi.org/project/agilab/
.. image:: https://img.shields.io/badge/License-BSD%203--Clause-blue.svg
   :target: https://opensource.org/licenses/BSD-3-Clause
.. image:: https://img.shields.io/pypi/dm/agilab
.. image:: https://thalesgroup.github.io/agilab/tests.svg
   :target: https://thalesgroup.github.io/agilab/tests.svg
.. image:: https://thalesgroup.github.io/agilab/coverage.svg
   :target: https://thalesgroup.github.io/agilab/coverage.svg
.. image:: https://img.shields.io/github/stars/ThalesGroup/agilab.svg
   :target: https://github.com/ThalesGroup/agilab
.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
.. image:: https://img.shields.io/badge/docs-online-brightgreen.svg
   :target: https://thalesgroup.github.io/agilab
.. image:: https://img.shields.io/badge/ORCID-0009--0003--5375--368X-A6CE39?logo=orcid
   :target: https://orcid.org/0009-0003-5375-368X


AGILAB Open Source Project
==========================

AGILAB `BSD license <https://github.com/ThalesGroup/agilab/blob/main/LICENSE>`_ project purpose is to explore AI for engineering. It is designed to help engineers quickly experiment with AI-driven methods.
See the `documentation <https://thalesgroup.github.io/agilab>`_.

Install and Execution for enduser
--------------------------------

.. code-block:: bash

   mkdir agi-workspace && cd agi-workspace
   uv init --bare
   uv add agilab
   uv run agilab --openai-api-key "your-api-key"

Install for developers
----------------------

.. tabs::

   .. tab:: Windows

      .. code-block:: powershell

         unzip agilab.zip
         cd agilab/src/agilab/fwk/gui
         powershell.exe -ExecutionPolicy Bypass -File .\install.ps1 --openai-api-key "your-api-key"

   .. tab:: Linux

      .. code-block:: bash

         git clone https://github.com/ThalesGroup/agilab
         cd agilab/ agilab/src/agilab/fwk/gui
         ./install.sh --openai-api-key "your-api-key" --cluster-ssh-credentials "username:[password]"

      Note: the password is provided only for demo restricted to posix linux os, see the
      `key-generation <key-generation.md>`_ page for a more secure alternative.

AGILab Execution
----------------

.. code-block:: bash

   cd agilab/src/agilab/fwk/gui
   uv run agilab
