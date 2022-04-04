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


@pytest.mark.parametrize(
    ["toml", "expected"],
    [["FLIT_TOML", "flit_core.buildapi"],
     ["SETUPTOOLS_TOML", "setuptools.build_meta"],
     ["NO_BUILD_BACKEND_TOML", ""],
     ["NO_BUILD_SYSTEM_TOML", ""],
     [None, ""],
     ])
def test_get_backend(tmp_path, capfd, toml, expected):
    if toml is not None:
        with open(tmp_path / "pyproject.toml", "w") as f:
            f.write(globals()[toml])

    assert 0 == main(["", "get-backend",
                      "--pyproject-toml", str(tmp_path / "pyproject.toml"),
                      "--output-fd", "1"])
    assert f"{expected}\n" == capfd.readouterr().out


@pytest.mark.parametrize(
    ["backend", "expected"],
    [("test.backend", "frobnicate-1-py3-none-any.whl"),
     ("test.backend:top_class", "frobnicate-2-py3-none-any.whl"),
     ("test.backend:top_class.sub_class", "frobnicate-3-py3-none-any.whl"),
     ])
def test_build_wheel(capfd, backend, expected):
    assert 0 == main(["", "build-wheel",
                      "--backend", backend,
                      "--output-fd", "1",
                      "--wheel-dir", "."])
    assert f"{expected}\n" == capfd.readouterr().out
