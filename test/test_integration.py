# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import contextlib
import os
import os.path
import pathlib
import shutil
import sys
import sysconfig
import zipfile

import pytest

from gpep517.__main__ import main

from test.common import IS_WINDOWS, EXE_SUFFIX


pytestmark = pytest.mark.xfail(
    IS_WINDOWS and sys.version_info[:2] == (3, 11) and
    getattr(sys, "pypy_version_info", ())[:3] == (7, 3, 19),
    reason="PyPy3.11 7.3.19 is broken on Windows "
    "(https://github.com/pypy/pypy/issues/5250)"
)


@contextlib.contextmanager
def pushd(path):
    orig_dir = pathlib.Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(orig_dir)


INTEGRATION_TESTS = [
    "flit_core",
    "hatchling",
    "pdm.pep517",
    "poetry.core",
    "setuptools",
    "setuptools-legacy",
]

INTEGRATION_TEST_EXTRA_DEPS = {
    "setuptools": ["wheel"],
    "setuptools-legacy": ["wheel"],
}


@pytest.mark.xfail(getattr(sys, "pypy_version_info", (0, 0, 0))[:3]
                   == (7, 3, 16) and IS_WINDOWS,
                   reason="PyPy 7.3.16 is broken on Windows")
@pytest.mark.parametrize("buildsys", INTEGRATION_TESTS)
def test_integration(tmp_path, capfd, buildsys, verify_zipfile_cleanup,
                     distutils_cache_cleanup):
    pytest.importorskip(buildsys.split("-", 1)[0])
    for dep in INTEGRATION_TEST_EXTRA_DEPS.get(buildsys, []):
        pytest.importorskip(dep)

    shutil.copytree(pathlib.Path("test/integration") / buildsys, tmp_path,
                    dirs_exist_ok=True)

    with pushd(tmp_path):
        assert 0 == main(["", "build-wheel",
                          "--output-fd", "1",
                          "--wheel-dir", "."])
    pkg = "testpkg-1"
    wheel_name = f"{pkg}-py3-none-any.whl"
    assert wheel_name == capfd.readouterr().out.splitlines()[-1]

    with zipfile.ZipFile(tmp_path / wheel_name, "r") as zipf:
        assert [
            "testpkg/__init__.py",
            "testpkg/datafile.txt",
        ] == sorted(x for x in zipf.namelist()
                    if not x.startswith(f"{pkg}.dist-info"))
        assert (b"[console_scripts]\nnewscript=testpkg:entry_point" ==
                zipf.read(f"{pkg}.dist-info/entry_points.txt")
                .strip().replace(b" ", b""))
        assert ({zipfile.ZIP_STORED}
                == {x.compress_type for x in zipf.infolist()})


@pytest.mark.xfail(getattr(sys, "pypy_version_info", (0, 0, 0))[:3]
                   == (7, 3, 16) and IS_WINDOWS,
                   reason="PyPy 7.3.16 is broken on Windows")
@pytest.mark.parametrize("buildsys", INTEGRATION_TESTS)
def test_integration_install(tmp_path, buildsys, verify_zipfile_cleanup,
                             distutils_cache_cleanup):
    pytest.importorskip(buildsys.split("-", 1)[0])
    for dep in INTEGRATION_TEST_EXTRA_DEPS.get(buildsys, []):
        pytest.importorskip(dep)

    shutil.copytree(pathlib.Path("test/integration") / buildsys, tmp_path,
                    dirs_exist_ok=True)

    destdir = tmp_path / "install"
    with pushd(tmp_path):
        assert 0 == main(["", "install-from-source",
                          "--destdir", str(destdir),
                          "--prefix", "/usr"])

    sitedir = destdir / (sysconfig.get_path("purelib", vars={"base": "/usr"})
                         .lstrip(os.path.sep))
    scriptdir = destdir / (sysconfig.get_path("scripts", vars={"base": "/usr"})
                           .lstrip(os.path.sep))
    assert all(dict((x, os.path.exists(x)) for x in
                    [f"{scriptdir}/newscript{EXE_SUFFIX}",
                     f"{sitedir}/testpkg/__init__.py",
                     f"{sitedir}/testpkg/datafile.txt",
                     ]).values())
