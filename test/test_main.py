import os
import pathlib
import sys
import sysconfig

import pytest

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
