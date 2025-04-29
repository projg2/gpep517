# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import contextlib
import importlib.machinery
import importlib.util
import os
import pathlib
import sysconfig
import typing

import pytest

from gpep517 import __version__
from gpep517.__main__ import main, ALL_OPT_LEVELS

from test.common import IS_WINDOWS, EXE_SUFFIX


def all_files(top_path):
    for cur_dir, sub_dirs, sub_files in os.walk(top_path):
        if cur_dir.endswith(".dist-info"):
            yield (pathlib.Path(cur_dir).relative_to(top_path), None)
            continue
        for f in sub_files:
            file_path = pathlib.Path(cur_dir) / f
            if f.endswith(".pyc"):
                # for .pyc files, we're interested in whether the correct
                # source path was embedded inside it
                loader = importlib.machinery.SourcelessFileLoader(
                    "testpkg", file_path)
                data = pathlib.Path(loader.get_code("testpkg").co_filename)
            elif f.endswith(".exe"):
                data = ""
            else:
                data = file_path.read_text().splitlines()[0]
            yield (file_path.relative_to(top_path),
                   (os.access(file_path, os.X_OK), data))


@pytest.mark.parametrize(["optimize"], [(None,), ("0",), ("1,2",), ("all",)])
@pytest.mark.parametrize(["prefix"], [("/usr",), ("/eprefix/usr",)])
@pytest.mark.parametrize(["overwrite"], [(False,), (True,)])
def test_install_wheel(tmp_path,
                       optimize: typing.Optional[str],
                       prefix: str,
                       overwrite: bool):
    args = (["", "install-wheel",
             "--destdir", str(tmp_path),
             "--interpreter", "/usr/bin/pythontest",
             "test/test-pkg/dist/test-1-py3-none-any.whl"] +
            (["--prefix", prefix] if prefix != "/usr" else []) +
            (["--optimize", optimize]
             if optimize is not None else []))
    assert 0 == main(args)

    expected_overwrite = (contextlib.nullcontext() if overwrite
                          else pytest.raises(FileExistsError))
    if overwrite:
        args.append("--overwrite")
    with expected_overwrite:
        assert 0 == main(args)

    expected_shebang = f"#!{str(pathlib.Path('/usr/bin/pythontest'))}"
    ep_shebang = "" if IS_WINDOWS else expected_shebang
    prefix = prefix.lstrip("/")
    bindir = sysconfig.get_path("scripts", vars={"base": ""})
    incdir = sysconfig.get_path("include", vars={"installed_base": ""})
    sitedir = sysconfig.get_path("purelib", vars={"base": ""})

    # everything is +x on Windows
    nonexec = True if IS_WINDOWS else False

    expected = {
        pathlib.Path(f"{prefix}{bindir}/newscript{EXE_SUFFIX}"):
        (True, ep_shebang),
        pathlib.Path(f"{prefix}{bindir}/oldscript"): (True, expected_shebang),
        pathlib.Path(f"{prefix}{incdir}/test/test.h"):
        (nonexec, "#define TEST_HEADER 1"),
        pathlib.Path(f"{prefix}{sitedir}/test-1.dist-info"): None,
        pathlib.Path(f"{prefix}{sitedir}/testpkg/__init__.py"):
        (nonexec, '"""A test package"""'),
        pathlib.Path(f"{prefix}{sitedir}/testpkg/datafile.txt"):
        (nonexec, "data"),
        pathlib.Path(f"{prefix}/share/test/datafile.txt"): (nonexec, "data"),
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
        expected[pathlib.Path(pyc)] = (nonexec, pathlib.Path(f"/{init_mod}"))

    assert expected == dict(all_files(tmp_path))


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
