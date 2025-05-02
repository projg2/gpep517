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
                data = (file_path.read_text() or "\n").splitlines()[0]
            yield (file_path.relative_to(top_path),
                   (os.access(file_path, os.X_OK),
                    file_path.is_symlink(),
                    data))


@pytest.mark.parametrize("optimize", [None, "0", "1,2", "all"])
@pytest.mark.parametrize("prefix", ["/usr", "/eprefix/usr"])
@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("symlink_pyc", [False, True])
def test_install_wheel(tmp_path,
                       optimize: typing.Optional[str],
                       prefix: str,
                       overwrite: bool,
                       symlink_pyc: bool,
                       ):
    args = (["", "install-wheel",
             "--destdir", str(tmp_path),
             "--interpreter", "/usr/bin/pythontest",
             "test/test-pkg/dist/test-1-py3-none-any.whl"] +
            (["--prefix", prefix] if prefix != "/usr" else []) +
            (["--optimize", optimize]
             if optimize is not None else []) +
            (["--symlink-pyc"] if symlink_pyc else [])
            )
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
        (True, False, ep_shebang),
        pathlib.Path(f"{prefix}{bindir}/oldscript"):
        (True, False, expected_shebang),
        pathlib.Path(f"{prefix}{incdir}/test/test.h"):
        (nonexec, False, "#define TEST_HEADER 1"),
        pathlib.Path(f"{prefix}{sitedir}/test-1.dist-info"): None,
        pathlib.Path(f"{prefix}{sitedir}/testpkg/__init__.py"):
        (nonexec, False, '"""A test package"""'),
        pathlib.Path(f"{prefix}{sitedir}/testpkg/datafile.txt"):
        (nonexec, False, "data"),
        pathlib.Path(f"{prefix}/share/test/datafile.txt"):
        (nonexec, False, "data"),
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
        expected[pathlib.Path(pyc)] = (
            nonexec,
            # our only symlinking opportunity is 1 -> 0
            symlink_pyc and opt == 1 and 0 in opt_levels,
            pathlib.Path(f"/{init_mod}"))

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


@pytest.mark.skipif(IS_WINDOWS, reason="--symlink-to not supported on Windows")
@pytest.mark.parametrize("optimize", [None, "all"])
@pytest.mark.parametrize("modification", ["",
                                          "remove-files",
                                          "remove-dir",
                                          "modify-file",
                                          ])
@pytest.mark.parametrize("symlink_pyc", [False, True])
def test_install_symlink_to(tmp_path,
                            optimize: typing.Optional[str],
                            modification: str,
                            symlink_pyc: bool,
                            ) -> None:
    args = (["", "install-wheel",
             "--destdir", str(tmp_path),
             "test/symlink-pkg/dist/foo-0-py3-none-any.whl"] +
            (["--optimize", optimize] if optimize is not None else []) +
            (["--symlink-pyc"] if symlink_pyc else [])
            )
    assert 0 == main(args + ["--prefix", "/first"])

    sitedir = pathlib.PurePath(
        sysconfig.get_path("purelib", vars={"base": "."}))
    to_parent = pathlib.PurePath(
        *(len(sitedir.relative_to(sitedir.anchor).parts) * ("..",)))
    symlink_to = to_parent / "../first" / sitedir

    if modification == "remove-files":
        tmp_path.joinpath("first", sitedir, "foo/a.py").unlink()
        tmp_path.joinpath("first", sitedir, "foo/data/b.txt").unlink()
    elif modification == "remove-dir":
        tmp_path.joinpath("first", sitedir, "foo/data/a.txt").unlink()
        tmp_path.joinpath("first", sitedir, "foo/data/b.txt").unlink()
        tmp_path.joinpath("first", sitedir, "foo/data/c.txt").unlink()
        tmp_path.joinpath("first", sitedir, "foo/data").rmdir()
    elif modification == "modify-file":
        tmp_path.joinpath("first", sitedir, "foo/b.py").write_text(
            '"""b modified"""')
        tmp_path.joinpath("first", sitedir, "foo/data/c.txt").write_text(
            "c modified")
    else:
        assert not modification

    assert 0 == main(args + ["--prefix", "/second",
                             "--symlink-to", str(symlink_to)])

    expected = {}

    for top_dir in ("first", "second"):
        expect_symlink = top_dir != "first"
        expected.update(
            {pathlib.Path(f"{top_dir}/{sitedir}/foo/__init__.py"):
             (False, expect_symlink, ""),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/a.py"):
             (False, expect_symlink, '"""a module"""'),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/b.py"):
             (False, expect_symlink, '"""b module"""'),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/a.txt"):
             (False, expect_symlink, "a file"),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/b.txt"):
             (False, expect_symlink, "b file"),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/c.txt"):
             (False, expect_symlink, "c file"),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/sub/__init__.py"):
             (False, expect_symlink, ""),
             pathlib.Path(f"{top_dir}/{sitedir}/foo-0.dist-info"): None,
             })

    opt_levels = []
    if optimize == "all":
        opt_levels = ALL_OPT_LEVELS
        for path in list(expected):
            if not path.name.endswith(".py"):
                continue
            for opt in opt_levels:
                pyc = importlib.util.cache_from_source(
                    path, optimization=opt if opt != 0 else "")
                expected[pathlib.Path(pyc)] = (
                    False,
                    symlink_pyc and
                    (opt == 1 or (opt != 0 and path.name == "__init__.py")),
                    pathlib.Path("/", path))

    if modification == "remove-files":
        del expected[pathlib.Path(f"first/{sitedir}/foo/a.py")]
        del expected[pathlib.Path(f"first/{sitedir}/foo/data/b.txt")]
        expected.update({
            pathlib.Path(f"second/{sitedir}/foo/a.py"):
            (False, False, '"""a module"""'),
            pathlib.Path(f"second/{sitedir}/foo/data/b.txt"):
            (False, False, "b file"),
        })
    elif modification == "remove-dir":
        del expected[pathlib.Path(f"first/{sitedir}/foo/data/a.txt")]
        del expected[pathlib.Path(f"first/{sitedir}/foo/data/b.txt")]
        del expected[pathlib.Path(f"first/{sitedir}/foo/data/c.txt")]
        expected.update({
            pathlib.Path(f"second/{sitedir}/foo/data/a.txt"):
            (False, False, "a file"),
            pathlib.Path(f"second/{sitedir}/foo/data/b.txt"):
            (False, False, "b file"),
            pathlib.Path(f"second/{sitedir}/foo/data/c.txt"):
            (False, False, "c file"),
        })
    elif modification == "modify-file":
        expected.update({
            pathlib.Path(f"first/{sitedir}/foo/b.py"):
            (False, False, '"""b modified"""'),
            pathlib.Path(f"first/{sitedir}/foo/data/c.txt"):
            (False, False, "c modified"),
            pathlib.Path(f"second/{sitedir}/foo/b.py"):
            (False, False, '"""b module"""'),
            pathlib.Path(f"second/{sitedir}/foo/data/c.txt"):
            (False, False, "c file"),
        })

    assert expected == dict(all_files(tmp_path))


@pytest.mark.skipif(IS_WINDOWS, reason="--symlink-to not supported on Windows")
@pytest.mark.parametrize("optimize", [None, "all"])
@pytest.mark.parametrize("modify", [False, True])
def test_install_symlink_chain(tmp_path,
                               optimize: typing.Optional[str],
                               modify: bool,
                               ) -> None:
    args = (["", "install-wheel",
             "--destdir", str(tmp_path),
             "test/symlink-pkg/dist/foo-0-py3-none-any.whl"] +
            (["--optimize", optimize] if optimize is not None else []))
    assert 0 == main(args + ["--prefix", "/first"])

    sitedir = pathlib.Path(
        sysconfig.get_path("purelib", vars={"base": "."}))
    if modify:
        mod_file = tmp_path.joinpath("first", sitedir, "foo/a.py")
        mod_file.write_text('"""a modified"""')

    to_parent = pathlib.Path(
        *(len(sitedir.relative_to(sitedir.anchor).parts) * ("..",)))
    symlink_to_first = to_parent / "../first" / sitedir

    assert 0 == main(args + ["--prefix", "/second",
                             "--symlink-to", str(symlink_to_first)])

    if modify:
        mod_file = tmp_path.joinpath("second", sitedir, "foo/b.py")
        mod_file.unlink()
        mod_file.write_text('"""b modified"""')

    symlink_to_second = to_parent / "../second" / sitedir
    assert 0 == main(args + ["--prefix", "/third",
                             "--symlink-to", str(symlink_to_second)])

    if modify:
        mod_file = tmp_path.joinpath("third", sitedir, "foo/data/a.txt")
        mod_file.unlink()
        mod_file.write_text('a modified')

    symlink_to_third = to_parent / "../third" / sitedir
    assert 0 == main(args + ["--prefix", "/fourth",
                             "--symlink-to", str(symlink_to_third)])

    expected = {}
    for top_dir in ("first", "second", "third", "fourth"):
        expect_symlink = top_dir != "first"
        expected.update(
            {pathlib.Path(f"{top_dir}/{sitedir}/foo/__init__.py"):
             (False, expect_symlink, ""),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/a.py"):
             (False, expect_symlink, '"""a module"""'),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/b.py"):
             (False, expect_symlink, '"""b module"""'),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/a.txt"):
             (False, expect_symlink, "a file"),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/b.txt"):
             (False, expect_symlink, "b file"),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/c.txt"):
             (False, expect_symlink, "c file"),
             pathlib.Path(f"{top_dir}/{sitedir}/foo/sub/__init__.py"):
             (False, expect_symlink, ""),
             pathlib.Path(f"{top_dir}/{sitedir}/foo-0.dist-info"): None
             })

    expected_links = {}
    for top_dir in ("second", "third", "fourth"):
        expected_links.update(
            {pathlib.Path(f"{top_dir}/{sitedir}/foo/__init__.py"):
             pathlib.Path("..") / symlink_to_first / "foo/__init__.py",
             pathlib.Path(f"{top_dir}/{sitedir}/foo/a.py"):
             pathlib.Path("..") / symlink_to_first / "foo/a.py",
             pathlib.Path(f"{top_dir}/{sitedir}/foo/b.py"):
             pathlib.Path("..") / symlink_to_first / "foo/b.py",
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/a.txt"):
             pathlib.Path("../..") / symlink_to_first / "foo/data/a.txt",
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/b.txt"):
             pathlib.Path("../..") / symlink_to_first / "foo/data/b.txt",
             pathlib.Path(f"{top_dir}/{sitedir}/foo/data/c.txt"):
             pathlib.Path("../..") / symlink_to_first / "foo/data/c.txt",
             pathlib.Path(f"{top_dir}/{sitedir}/foo/sub/__init__.py"):
             pathlib.Path("../..") / symlink_to_first / "foo/sub/__init__.py",
             })

    if modify:
        expected.update(
            {pathlib.Path(f"first/{sitedir}/foo/a.py"):
             (False, False, '"""a modified"""'),
             pathlib.Path(f"second/{sitedir}/foo/a.py"):
             (False, False, '"""a module"""'),
             pathlib.Path(f"second/{sitedir}/foo/b.py"):
             (False, False, '"""b modified"""'),
             pathlib.Path(f"third/{sitedir}/foo/b.py"):
             (False, False, '"""b module"""'),
             pathlib.Path(f"third/{sitedir}/foo/data/a.txt"):
             (False, False, "a modified"),
             pathlib.Path(f"fourth/{sitedir}/foo/data/a.txt"):
             (False, False, "a file"),
             })
        expected_links.update(
            {pathlib.Path(f"third/{sitedir}/foo/a.py"):
             pathlib.Path("..") / symlink_to_second / "foo/a.py",
             pathlib.Path(f"fourth/{sitedir}/foo/a.py"):
             pathlib.Path("..") / symlink_to_second / "foo/a.py",
             pathlib.Path(f"fourth/{sitedir}/foo/b.py"):
             pathlib.Path("..") / symlink_to_third / "foo/b.py",
             })
        del expected_links[pathlib.Path(f"second/{sitedir}/foo/a.py")]
        del expected_links[pathlib.Path(f"second/{sitedir}/foo/b.py")]
        del expected_links[pathlib.Path(f"third/{sitedir}/foo/b.py")]
        del expected_links[pathlib.Path(f"third/{sitedir}/foo/data/a.txt")]
        del expected_links[pathlib.Path(f"fourth/{sitedir}/foo/data/a.txt")]

    opt_levels = []
    if optimize == "all":
        opt_levels = ALL_OPT_LEVELS
        for path in list(expected):
            if not path.name.endswith(".py"):
                continue
            for opt in opt_levels:
                pyc = importlib.util.cache_from_source(
                    path, optimization=opt if opt != 0 else "")
                expected[pathlib.Path(pyc)] = (
                    False, False, pathlib.Path("/", path))

    assert expected == dict(all_files(tmp_path))

    assert expected_links == {path: tmp_path.joinpath(path).readlink()
                              for path, path_data in expected.items()
                              if path_data is not None and path_data[1]}
