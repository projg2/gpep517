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


Change log
==========
v19
  - detect symlink chains when using ``--symlink-to`` and resolve them,
    so that the subsequent symlinks point to the actual file
  - add a ``--symlink-pyc`` option to symlink identical ``.pyc`` across
    optimization levels

v18
  - add an ``--overwrite`` option to install commands to permit
    overwriting files in ``--destdir`` instead of throwing an error
  - add a ``--symlink-to`` option to install commands that can be used
    to cross-link multiple installs of the same wheel to save space

v17
  - error on ``--sysroot`` on Windows

v16
  - fix potential crash when using ``--output-fd 1`` or ``2``

v15
  - replace prefix rewriting with the ability to specify ``--prefix``
    for building wheels, making it consistent with prefix overrides
    used while installing

v14
  - add support for offset prefix rewriting (``--rewrite-prefix-from``
    and ``--rewrite-prefix-to``) to support Gentoo cross-prefix builds;
    thanks to Chewi for the patch

v13
  - restore PyPy support for ``--sysroot`` (Gentoo's PyPy3 package
    was buggy)

v12
  - add ``--sysroot`` option for experimental cross-compilation support

v11
  - test fixes and refactorings

v10
  - create specified ``--wheel-dir`` automatically

v9
  - add ``--optimize`` option to byte-compile while installing
  - include implicit setuptools fallback in ``build-wheel``
  - add ``install-from-source`` command combining building a wheel
    and installing it
  - add progress reporting via logging

v8
  - improve ``.pyc`` checking to use verification data from the file header

v7
  - add ``verify-pyc`` command to aid verifying whether all Python modules
    were compiled to ``.pyc`` files correctly

v6
  - strip current working directory from ``sys.path`` prior to importing
    the build backend

v5
  - fix zipfile hack not to break reading compressed zipfiles

v4
  - patch zipfile compression out by default to improve performance
  - fix Python < 3.9 compatibility

v3
  - add ``--config-json`` to specify backend options

v2
  - fix not preserving ``backend-path`` for backend invocation
  - support tomllib in Python 3.11+

v1
  - initial version with wheel building and installation support


Commands
========
gpep517 implements the following commands:

1. ``get-backend`` to read ``build-backend`` from ``pyproject.toml``
   (auxiliary command).

2. ``build-wheel`` to call the respeective PEP 517 backend in order
   to produce a wheel.

3. ``install-wheel`` to install a wheel into the specified directory,

4. ``install-from-source`` that combines building a wheel and installing
   it (without leaving the artifacts),

5. ``verify-pyc`` to verify that the ``.pyc`` files in the specified
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


Examples
========
The simplest way to install a package from the current directory
is to use the ``install-from-source`` command, e.g.:

.. code-block:: bash

    gpep517 install-from-source --destdir install --optimize all

gpep517 can also be used as a thin wrapper over the installer_ package,
to install a prebuilt wheel:

.. code-block:: bash

    gpep517 install-wheel --destdir install --optimize all \
        gpep517-8-py3-none-any.whl

Alternatively, the wheel can be built and installed separately.
Notably, this leaves the built wheel in the specified directory
for reuse:

.. code-block:: bash

    set -e
    mkdir -p dist
    wheel_name=$(
        # the output forwarding trick guarantees that the underlying
        # backend will not output into ${wheel_name}
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
