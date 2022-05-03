import contextlib
import io
import os
import pathlib
import shutil
import sys
import sysconfig
import zipfile

import pytest

from gpep517 import __version__
from gpep517.__main__ import main


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
backend-path = ["test/sub-path"]
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
def test_build_wheel(capfd, backend, expected):
    orig_path = list(sys.path)
    assert 0 == main(["", "build-wheel",
                      "--backend", backend,
                      "--output-fd", "1",
                      "--wheel-dir", "."])
    assert f"{expected}\n" == capfd.readouterr().out
    assert orig_path == sys.path


def test_build_wheel_backend_path(tmp_path, capfd):
    with open(tmp_path / "pyproject.toml", "w") as f:
        f.write(TEST_BACKEND_TOML)

    orig_path = list(sys.path)
    assert 0 == main(["", "build-wheel",
                      "--output-fd", "1",
                      "--pyproject-toml", str(tmp_path / "pyproject.toml"),
                      "--wheel-dir", "."])
    assert "frobnicate-4-py3-none-any.whl\n" == capfd.readouterr().out
    assert orig_path == sys.path


@pytest.mark.parametrize(
    ["settings", "expected"],
    [("{}", "frobnicate-5-py3-none-any.whl"),
     ('{"version": 6}', "frobnicate-6-py3-none-any.whl"),
     ])
def test_build_wheel_config_settings(tmp_path, capfd, settings, expected):
    orig_path = list(sys.path)
    assert 0 == main(["", "build-wheel",
                      "--backend", "test.backend",
                      "--config-json", settings,
                      "--output-fd", "1",
                      "--wheel-dir", "."])
    assert f"{expected}\n" == capfd.readouterr().out
    assert orig_path == sys.path


def all_files(top_path):
    for cur_dir, sub_dirs, sub_files in os.walk(top_path):
        if cur_dir.endswith(".dist-info"):
            yield (str(pathlib.Path(cur_dir).relative_to(top_path)), None)
            continue
        for f in sub_files:
            file_path = pathlib.Path(cur_dir) / f
            yield (str(file_path.relative_to(top_path)),
                   (os.access(file_path, os.X_OK),
                    file_path.read_text().splitlines()[0]))


@pytest.mark.parametrize(["prefix"], [("/usr",), ("/eprefix/usr",)])
def test_install_wheel(tmp_path, prefix):
    assert 0 == main(["", "install-wheel",
                      "--destdir", str(tmp_path),
                      "--interpreter", "/usr/bin/pythontest",
                      "test/test-pkg/dist/test-1-py3-none-any.whl"] +
                     (["--prefix", prefix] if prefix != "/usr" else []))

    expected_shebang = "#!/usr/bin/pythontest"
    prefix = prefix.lstrip("/")
    incdir = sysconfig.get_path("include", vars={"installed_base": ""})
    sitedir = sysconfig.get_path("purelib", vars={"base": ""})

    assert {
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
    } == dict(all_files(tmp_path))


def test_build_self(tmp_path, capfd):
    orig_path = list(sys.path)
    assert 0 == main(["", "build-wheel",
                      "--allow-compressed",
                      "--output-fd", "1",
                      "--wheel-dir", str(tmp_path)])
    pkg = f"gpep517-{__version__}"
    wheel_name = f"{pkg}-py3-none-any.whl"
    assert f"{wheel_name}\n" == capfd.readouterr().out
    assert orig_path == sys.path

    with zipfile.ZipFile(tmp_path / wheel_name, "r") as zipf:
        assert all(x in zipf.namelist() for x in [
            f"{pkg}.dist-info/METADATA",
            f"{pkg}.dist-info/entry_points.txt",
            "gpep517/__init__.py",
            "gpep517/__main__.py",
        ])
        # NB: we're relying on flit_core defaulting to deflate
        assert ({zipfile.ZIP_DEFLATED}
                == {x.compress_type for x in zipf.infolist()})


@contextlib.contextmanager
def pushd(path):
    orig_dir = pathlib.Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(orig_dir)


@pytest.mark.parametrize(
    ["buildsys", "extra_deps"],
    [("flit_core", []),
     ("hatchling", []),
     ("pdm.pep517", []),
     ("poetry.core", []),
     ("setuptools", ["wheel"]),
     ])
def test_integration(tmp_path, capfd, buildsys, extra_deps):
    pytest.importorskip(buildsys)
    for dep in extra_deps:
        pytest.importorskip(dep)

    shutil.copytree(pathlib.Path("test/integration") / buildsys, tmp_path,
                    dirs_exist_ok=True)

    orig_path = list(sys.path)
    with pushd(tmp_path):
        assert 0 == main(["", "build-wheel",
                          "--output-fd", "1",
                          "--wheel-dir", "."])
    pkg = "testpkg-1"
    wheel_name = f"{pkg}-py3-none-any.whl"
    assert wheel_name == capfd.readouterr().out.splitlines()[-1]
    assert orig_path == sys.path

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

    # verify that we've reverted our patching
    with io.BytesIO() as f:
        with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("test.txt", "data")
            assert (zipfile.ZIP_DEFLATED ==
                    zipf.getinfo("test.txt").compress_type)
