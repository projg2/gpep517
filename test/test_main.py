# (c) 2022-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sys
import sysconfig
import zipfile

import pytest

from gpep517 import __version__
from gpep517.__main__ import main, ALL_OPT_LEVELS

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


@pytest.fixture
def verify_mod_cleanup():
    def get_modules():
        # _sysconfigdata* gets imported when we query sysconfig
        return sorted(
            x for x in sys.modules if not x.startswith("_sysconfigdata"))

    orig_modules = get_modules()
    orig_path = list(sys.path)
    yield
    assert orig_path == sys.path
    assert orig_modules == get_modules()


@pytest.fixture
def verify_zipfile_cleanup(tmp_path):
    """Verify that we are reverting zipfile patching correctly"""
    yield
    with open(tmp_path / "write.txt", "wb") as f:
        f.write(b"data")
    with io.BytesIO() as f:
        with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            with zipf.open("open.txt", "w") as f:
                f.write(b"data")
            zipf.writestr("writestr.txt", b"data")
            zipf.write(tmp_path / "write.txt", "write.txt")
            assert ({zipfile.ZIP_DEFLATED}
                    == {x.compress_type for x in zipf.infolist()})


@pytest.fixture
def distutils_cache_cleanup():
    try:
        yield
    finally:
        if distutils_sysconfig is not None and hasattr(distutils_sysconfig,
                                                       "_config_vars"):
            distutils_sysconfig._config_vars = None


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


def all_files(top_path):
    for cur_dir, sub_dirs, sub_files in os.walk(top_path):
        if cur_dir.endswith(".dist-info"):
            yield (str(pathlib.Path(cur_dir).relative_to(top_path)), None)
            continue
        for f in sub_files:
            file_path = pathlib.Path(cur_dir) / f
            if f.endswith(".pyc"):
                # for .pyc files, we're interested in whether the correct
                # source path was embedded inside it
                loader = importlib.machinery.SourcelessFileLoader(
                    "testpkg", file_path)
                data = loader.get_code("testpkg").co_filename
            else:
                data = file_path.read_text().splitlines()[0]
            yield (str(file_path.relative_to(top_path)),
                   (os.access(file_path, os.X_OK), data))


@pytest.mark.parametrize(["optimize"], [(None,), ("0",), ("1,2",), ("all",)])
@pytest.mark.parametrize(["prefix"], [("/usr",), ("/eprefix/usr",)])
def test_install_wheel(tmp_path, optimize, prefix):
    assert 0 == main(["", "install-wheel",
                      "--destdir", str(tmp_path),
                      "--interpreter", "/usr/bin/pythontest",
                      "test/test-pkg/dist/test-1-py3-none-any.whl"] +
                     (["--prefix", prefix] if prefix != "/usr" else []) +
                     (["--optimize", optimize]
                      if optimize is not None else []))

    expected_shebang = "#!/usr/bin/pythontest"
    prefix = prefix.lstrip("/")
    incdir = sysconfig.get_path("include", vars={"installed_base": ""})
    sitedir = sysconfig.get_path("purelib", vars={"base": ""})

    expected = {
        f"{prefix}/bin/newscript": (True, expected_shebang),
        f"{prefix}/bin/oldscript": (True, expected_shebang),
        f"{prefix}{incdir}/test/test.h":
        (False, "#define TEST_HEADER 1"),
        f"{prefix}{sitedir}/test-1.dist-info": None,
        f"{prefix}{sitedir}/testpkg/__init__.py":
        (False, '"""A test package"""'),
        f"{prefix}{sitedir}/testpkg/datafile.txt":
        (False, "data"),
        f"{prefix}/share/test/datafile.txt": (False, "data"),
    }

    opt_levels = []
    if optimize == "all":
        opt_levels = ALL_OPT_LEVELS
    elif optimize is not None:
        opt_levels = [int(x) for x in optimize.split(",")]
    init_mod = f"{prefix}{sitedir}/testpkg/__init__.py"
    for opt in opt_levels:
        pyc = importlib.util.cache_from_source(
            init_mod, optimization=opt if opt != 0 else "")
        expected[pyc] = (False, "/" + init_mod)

    assert expected == dict(all_files(tmp_path))


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


def test_install_self(tmp_path):
    pytest.importorskip("flit_core")
    assert 0 == main(["", "install-from-source",
                      "--allow-compressed",
                      "--destdir", str(tmp_path),
                      "--prefix", "/usr"])

    pkg = f"gpep517-{__version__}"
    sitedir = tmp_path / (sysconfig.get_path("purelib", vars={"base": "/usr"})
                          .lstrip(os.path.sep))
    assert all(dict((x, os.path.exists(x)) for x in
                    [f"{sitedir}/{pkg}.dist-info/METADATA",
                     f"{sitedir}/{pkg}.dist-info/entry_points.txt",
                     f"{sitedir}/gpep517/__init__.py",
                     f"{sitedir}/gpep517/__main__.py",
                     ]).values())


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
    assert all(dict((x, os.path.exists(x)) for x in
                    [f"{destdir}/usr/bin/newscript",
                     f"{sitedir}/testpkg/__init__.py",
                     f"{sitedir}/testpkg/datafile.txt",
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
