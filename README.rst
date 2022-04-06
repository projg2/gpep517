=======
gpep517
=======

gpep517 is a minimal backend script to aid installing Python packages
through `PEP 517`_-compliant build systems.  Its main purpose is
to supplement Gentoo eclasses with the necessary Python code.


Commands
========
gpep517 implements three commands:

1. ``get-backend`` to read ``build-backend`` from ``pyproject.toml``.

2. ``build-wheel`` to call the respeective PEP 517 backend in order
   to produce a wheel.

3. ``install-wheel`` to install the wheel into specified directory.


Dependencies
============
gpep517 aims to minimize the dependency footprint to ease boostrap.
At the moment, it depends on two packages:

1. tomli_ for TOML parsing in Python < 3.11

2. installer_ for wheel installation


Example
=======
Example use (without error handling):

.. code-block:: bash

    backend=$(gpep517 get-backend)
    mkdir -p build
    wheel_name=$(
        gpep517 build-wheel --output-fd 3 --wheel-dir dist \
            --backend "${backend:-setuptools.build_meta:__legacy__}" \
            3>&1 >&2
    )
    gpep517 install-wheel --destdir install "dist/${wheel_name}"


.. _PEP 517: https://peps.python.org/pep-0517/
.. _tomli: https://pypi.org/project/tomli/
.. _installer: https://pypi.org/project/installer/
