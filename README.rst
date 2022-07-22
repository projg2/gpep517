=======
gpep517
=======

gpep517 is a minimal tool to aid building wheels for Python packages
through `PEP 517`_-compliant build systems and installing them.
The tool originated from Gentoo with its primary goals being absolutely
minimal dependency footprint to ease clean bootstrap without bundling
dependencies, and clean separation of functions to aid external package
managers.  It is the tool of choice for a world that does not revolve
around pip and venvs.


Commands
========
gpep517 implements the following commands:

1. ``get-backend`` to read ``build-backend`` from ``pyproject.toml``
   (auxiliary command).

2. ``build-wheel`` to call the respeective PEP 517 backend in order
   to produce a wheel.

3. ``install-wheel`` to install a wheel into the specified directory,

4. ``verify-pyc`` to verify that the ``.pyc`` files in the specified
   install tree are correct and up-to-date.


Dependencies
============
gpep517 aims to minimize the dependency footprint to ease bootstrap.
At the moment, it depends on two packages:

1. tomli_ for TOML parsing in Python < 3.11

2. installer_ for wheel installation

Additionally, PEP 517 build requires flit_core_.  However, the package
can be used from the source tree or manually installed without that
dependency.

Running the test suite requires pytest_ and flit_core_ (as provided
by the ``test`` extra).  Additional build systems can be installed
to extend integration testing (``test-full`` extra).  A tox_ file
is also provided to ease running tests.


Example
=======
Example use (without error handling):

.. code-block:: bash

    mkdir dist
    wheel_name=$(
        gpep517 build-wheel --output-fd 3 --wheel-dir dist \
            3>&1 >&2
    )
    gpep517 install-wheel --destdir install "dist/${wheel_name}"


.. _PEP 517: https://peps.python.org/pep-0517/
.. _tomli: https://pypi.org/project/tomli/
.. _installer: https://pypi.org/project/installer/
.. _flit_core: https://pypi.org/project/flit_core/
.. _pytest: https://pypi.org/project/pytest/
.. _tox: https://pypi.org/project/tox/
