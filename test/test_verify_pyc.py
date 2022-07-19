import compileall
import importlib.util
import sys
import sysconfig

from pathlib import Path

import pytest

from gpep517.__main__ import main


class TestVerifyPyc:
    prefix = "/usr"

    def d(self, path):
        return self.top_path / path.relative_to(path.root)

    @pytest.fixture(autouse=True)
    def make_data(self, tmp_path):
        self.top_path = tmp_path
        self.sitedir = Path(sysconfig.get_path("purelib",
                                               vars={"base": self.prefix}))
        self.d_sitedir = tmp_path / self.d(self.sitedir)

        self.d_sitedir.mkdir(parents=True)
        self.py = self.sitedir / "__init__.py"
        self.d_py = self.d(self.py)
        self.pyc = [Path(importlib.util.cache_from_source(str(self.py),
                                                          optimization=x))
                    for x in ("", 1, 2)]
        self.d_pyc = [self.d(pyc) for pyc in self.pyc]
        self.d_py.write_bytes(b"def foo():\n    pass\n")

    def compile(self, optimize=(0, 1, 2)):
        # TODO: we can remove the loop and just pass the tuple to optimize=
        # when we drop support for py38
        for opt in optimize:
            compileall.compile_dir(str(self.d_sitedir),
                                   ddir=str(self.sitedir),
                                   quiet=1,
                                   optimize=opt)

    def run_main(self):
        return main(["", "verify-pyc",
                     "--destdir", str(self.top_path),
                     "--prefix", self.prefix])

    def test_good(self, capsys):
        self.compile()
        assert 0 == self.run_main()
        assert capsys.readouterr().out == ""

    def test_missing_optlevel(self, capsys):
        self.compile(optimize=(0, 1))
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"missing:{self.pyc[2]}:{self.py}",
        ]

    def test_missing_all(self, capsys):
        assert 1 == self.run_main()
        assert set(capsys.readouterr().out.splitlines()) == {
            f"missing:{self.pyc[0]}:{self.py}",
            f"missing:{self.pyc[1]}:{self.py}",
            f"missing:{self.pyc[2]}:{self.py}",
        }

    def test_empty(self, capsys):
        self.compile()
        self.d_pyc[0].write_bytes(b"")
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"invalid:{self.pyc[0]}:{self.py}",
        ]

    def test_short(self, capsys):
        self.compile()
        with self.d_pyc[0].open("r+b") as f:
            f.truncate(3)
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"invalid:{self.pyc[0]}:{self.py}",
        ]

    def test_min_header(self, capsys):
        self.compile()
        with self.d_pyc[0].open("r+b") as f:
            f.truncate(16)
        assert 0 == self.run_main()
        assert capsys.readouterr().out == ""

    def test_magic_number_mismatch(self, capsys):
        self.compile()
        with self.d_pyc[0].open("r+b") as f:
            magic = f.read(2)
            magic = bytes((magic[0] ^ 0x01, magic[1]))
            f.seek(0)
            f.write(magic)
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"invalid:{self.pyc[0]}:{self.py}",
        ]

    def test_magic_fixed_mismatch(self, capsys):
        self.compile()
        with self.d_pyc[0].open("r+b") as f:
            f.seek(2)
            f.write(b"NO")
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"invalid:{self.pyc[0]}:{self.py}",
        ]

    @pytest.mark.parametrize("suffix", ["c", "o"])
    def test_py2_stray_impl(self, capsys, suffix):
        self.compile()
        pyc = Path(f"{self.py}{suffix}")
        # the contents should not matter
        self.d(pyc).write_bytes(b"")
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"stray:{pyc}",
        ]

    @pytest.mark.parametrize("suffix", ["c", "o"])
    def test_py2_stray_name(self, capsys, suffix):
        self.compile()
        pyc = self.py.parent / f"test.py{suffix}"
        # the contents should not matter
        self.d(pyc).write_bytes(b"")
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"stray:{pyc}",
        ]

    def test_py3_stray_impl(self, capsys):
        self.compile()
        # old version that's not supported by gpep517
        new_name = self.pyc[0].name.replace(sys.implementation.cache_tag,
                                            "cpython-32")
        pyc = self.pyc[0].parent / new_name
        self.d(pyc).write_bytes(b"")
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"stray:{pyc}",
        ]

    def test_py3_stray_name(self, capsys):
        self.compile()
        new_name = self.pyc[0].name.replace("__init__", "test")
        pyc = self.pyc[0].parent / new_name
        self.d(pyc).write_bytes(b"")
        assert 1 == self.run_main()
        assert capsys.readouterr().out.splitlines() == [
            f"stray:{pyc}",
        ]

    def test_no_py(self, capsys):
        self.compile()
        self.d_py.unlink()
        assert 1 == self.run_main()
        assert set(capsys.readouterr().out.splitlines()) == {
            f"stray:{self.pyc[0]}",
            f"stray:{self.pyc[1]}",
            f"stray:{self.pyc[2]}",
        }
