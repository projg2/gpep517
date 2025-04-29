# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import json
import pathlib
import sysconfig
import zipfile

import pytest

from gpep517 import __version__
from gpep517.__main__ import main

from test.common import IS_WINDOWS

try:
    import distutils.sysconfig as distutils_sysconfig
except ImportError:
    distutils_sysconfig = None


FLIT_TOML = """
[build-system]
requires = ["flit_core >=3.2,<4"]
build-backend = "flit_core.buildapi"
"""

SETUPTOOLS_TOML = """
[build-system]
requires = ["setuptools>=34.4", "wheel"]
build-backend = "setuptools.build_meta"
"""

NO_BUILD_BACKEND_TOML = """
[build-system]
requires = []
"""

NO_BUILD_SYSTEM_TOML = """
[stuff]
irrelevant = "yes"
"""

TEST_BACKEND_TOML = """
[build-system]
requires = []
build-backend = "backend"
backend-path = ["{path}"]
"""

ZIP_BACKEND_TOML = """
[build-system]
requires = []
build-backend = "test.backend:{backend}"
"""

SYSCONFIG_DATA = """
build_time_vars = {
    "CONFINCLUDEDIR": "/foo/include",
    "INCLUDEDIR": "/foo/include",
    "CONFINCLUDEPY": "/foo/include/python3.11",
    "INCLUDEPY": "/foo/include/python3.11",
    "LIBDIR": "/foo/lib",
    "SOABI": "cpython-311-i386-linux-gnu",
    "EXT_SUFFIX": ".cpython-311-i386-linux-gnu.so",
    "MULTIARCH": "i386-linux-gnu",
}
"""


@pytest.mark.parametrize(
    ["toml", "expected"],
    [("FLIT_TOML", "flit_core.buildapi"),
     ("SETUPTOOLS_TOML", "setuptools.build_meta"),
     ("NO_BUILD_BACKEND_TOML", ""),
     ("NO_BUILD_SYSTEM_TOML", ""),
     ("TEST_BACKEND_TOML", "backend"),
     (None, ""),
     ])
def test_get_backend(tmp_path, capfd, toml, expected):
    if toml is not None:
        with open(tmp_path / "pyproject.toml", "w") as f:
            f.write(globals()[toml])

    assert 0 == main(["", "get-backend",
                      "--pyproject-toml", str(tmp_path / "pyproject.toml")])
    assert f"{expected}\n" == capfd.readouterr().out


@pytest.mark.parametrize(
    ["backend", "expected"],
    [("test.backend", "frobnicate-1-py3-none-any.whl"),
     ("test.backend:top_class", "frobnicate-2-py3-none-any.whl"),
     ("test.backend:top_class.sub_class", "frobnicate-3-py3-none-any.whl"),
     ])
def test_build_wheel(capfd, backend, expected, verify_mod_cleanup):
    assert 0 == main(["", "build-wheel",
                      "--backend", backend,
                      "--output-fd", "1",
                      "--wheel-dir", "."])
    assert f"{expected}\n" == capfd.readouterr().out


def test_build_wheel_fallback(capfd, verify_mod_cleanup):
    assert 0 == main(["", "build-wheel",
                      "--fallback-backend", "test.backend",
                      "--output-fd", "1",
                      "--pyproject-toml", "enoent.toml",
                      "--wheel-dir", "."])
    assert "frobnicate-1-py3-none-any.whl\n" == capfd.readouterr().out


def test_build_wheel_no_fallback():
    with pytest.raises(RuntimeError):
        main(["", "build-wheel",
                  "--no-fallback-backend",
                  "--output-fd", "1",
                  "--pyproject-toml", "enoent.toml",
                  "--wheel-dir", "."])


@pytest.mark.parametrize(
    ("path", "expected"),
    [("test/sub-path", "frobnicate-4-py3-none-any.whl"),
     ("test", "frobnicate-1-py3-none-any.whl"),
     ])
def test_build_wheel_backend_path(tmp_path, capfd, path, expected,
                                  verify_mod_cleanup):
    with open(tmp_path / "pyproject.toml", "w") as f:
        f.write(TEST_BACKEND_TOML.format(path=path))

    assert 0 == main(["", "build-wheel",
                      "--output-fd", "1",
                      "--pyproject-toml", str(tmp_path / "pyproject.toml"),
                      "--wheel-dir", "."])
    assert f"{expected}\n" == capfd.readouterr().out


@pytest.mark.parametrize(
    ["settings", "expected"],
    [("{}", "frobnicate-5-py3-none-any.whl"),
     ('{"version": 6}', "frobnicate-6-py3-none-any.whl"),
     ])
def test_build_wheel_config_settings(tmp_path, capfd, settings, expected,
                                     verify_mod_cleanup):
    assert 0 == main(["", "build-wheel",
                      "--backend", "test.backend",
                      "--config-json", settings,
                      "--output-fd", "1",
                      "--wheel-dir", "."])
    assert f"{expected}\n" == capfd.readouterr().out


def test_build_self(tmp_path, capfd):
    pytest.importorskip("flit_core")
    assert 0 == main(["", "build-wheel",
                      "--allow-compressed",
                      "--output-fd", "1",
                      "--wheel-dir", str(tmp_path)])
    pkg = f"gpep517-{__version__}"
    wheel_name = f"{pkg}-py3-none-any.whl"
    assert f"{wheel_name}\n" == capfd.readouterr().out

    with zipfile.ZipFile(tmp_path / wheel_name, "r") as zipf:
        assert all(dict((x, x in zipf.namelist()) for x in
                        [f"{pkg}.dist-info/METADATA",
                         f"{pkg}.dist-info/entry_points.txt",
                         "gpep517/__init__.py",
                         "gpep517/__main__.py",
                         ]).values())


def test_backend_opening_zipfile_compressed(tmp_path, capfd,
                                            verify_mod_cleanup):
    with open(tmp_path / "pyproject.toml", "w") as f:
        f.write(ZIP_BACKEND_TOML.format(backend="zip_writestr_backend"))

    wheel_name = "frobnicate-7-py3-none-any.whl"
    with zipfile.ZipFile(tmp_path / "test.zip", "w") as zipf:
        zipf.writestr("test.txt", wheel_name)

    assert 0 == main(["", "build-wheel",
                      "--allow-compressed",
                      "--output-fd", "1",
                      "--pyproject-toml", str(tmp_path / "pyproject.toml"),
                      "--wheel-dir", str(tmp_path)])
    assert f"{wheel_name}\n" == capfd.readouterr().out

    with zipfile.ZipFile(tmp_path / wheel_name, "r") as zipf:
        assert ({zipfile.ZIP_DEFLATED}
                == {x.compress_type for x in zipf.infolist()})


@pytest.mark.parametrize(
    "backend",
    ["zip_open_backend",
     "zip_open_zinfo_backend",
     "zip_write_backend",
     "zip_writestr_backend",
     ])
def test_backend_opening_zipfile(tmp_path, capfd, backend, verify_mod_cleanup,
                                 verify_zipfile_cleanup):
    """Verify that we do not break opening compressed zips"""
    with open(tmp_path / "pyproject.toml", "w") as f:
        f.write(ZIP_BACKEND_TOML.format(backend=backend))

    wheel_name = "frobnicate-6-py3-none-any.whl"
    with zipfile.ZipFile(tmp_path / "test.zip", "w",
                         compression=zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr("test.txt", wheel_name)
        assert zipfile.ZIP_DEFLATED == zipf.getinfo("test.txt").compress_type

    assert 0 == main(["", "build-wheel",
                      "--output-fd", "1",
                      "--pyproject-toml", str(tmp_path / "pyproject.toml"),
                      "--wheel-dir", str(tmp_path)])
    assert f"{wheel_name}\n" == capfd.readouterr().out

    with zipfile.ZipFile(tmp_path / wheel_name, "r") as zipf:
        assert ({zipfile.ZIP_STORED}
                == {x.compress_type for x in zipf.infolist()})


@pytest.mark.skipif(IS_WINDOWS, reason="--sysroot not supported on Windows")
@pytest.mark.parametrize("prefix", [None, "/usr", "/new_prefix/usr"])
def test_sysroot(tmp_path, capfd, verify_mod_cleanup, distutils_cache_cleanup,
                 prefix):
    with open(tmp_path / "pyproject.toml", "w") as f:
        f.write(ZIP_BACKEND_TOML.format(backend="sysroot_backend"))

    default_prefix = sysconfig.get_config_var("installed_base")
    base_stdlib_path = (
        pathlib.Path(sysconfig.get_path("stdlib")).relative_to(default_prefix))

    norm_prefix_to = (prefix or default_prefix)
    tmp_prefix = tmp_path / pathlib.Path(norm_prefix_to).relative_to("/")
    stdlib_path = tmp_prefix / base_stdlib_path
    stdlib_path.mkdir(parents=True)
    (tmp_prefix / "foo/include/python3.11").mkdir(parents=True)
    with open(stdlib_path / "_sysconfigdata__linux_i386-linux-gnu.py",
              "w") as f:
        f.write(SYSCONFIG_DATA.replace("/foo", f"{norm_prefix_to}/foo"))

    assert 0 == main(["", "build-wheel",
                      "--allow-compressed",
                      "--output-fd", "1",
                      "--pyproject-toml", str(tmp_path / "pyproject.toml"),
                      "--sysroot", str(tmp_path),
                      "--wheel-dir", str(tmp_path)] +
                     (["--prefix", prefix] if prefix is not None else []))
    assert "data.json\n" == capfd.readouterr().out

    with open(tmp_path / "data.json", "r") as f:
        data = json.load(f)

    expected = {
        "CONFINCLUDEDIR": str(tmp_prefix / "foo/include"),
        "INCLUDEDIR": str(tmp_prefix / "foo/include"),
        "CONFINCLUDEPY": str(tmp_prefix / "foo/include/python3.11"),
        "INCLUDEPY": str(tmp_prefix / "foo/include/python3.11"),
        "LIBDIR": str(tmp_prefix / "foo/lib"),
        "SOABI": "cpython-311-i386-linux-gnu",
        "EXT_SUFFIX": ".cpython-311-i386-linux-gnu.so",
        "_platform": "i386-linux-gnu",
    }

    if distutils_sysconfig is not None:
        expected["_distutils"] = {
            "get_python_inc(False)": str(tmp_prefix /
                                         "foo/include/python3.11"),
            "get_python_inc(True)": str(tmp_prefix /
                                        "foo/include/python3.11"),
        }

    assert data == expected
