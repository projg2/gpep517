# (c) 2022-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import importlib.util
import os
import os.path
import struct
import typing

from pathlib import Path


class PEP552Header:
    def __init__(self, pyc_f):
        # per PEP 552, the header consists of:
        # 4-byte magic (16-bit uint + b"\r\n")
        # 4-byte flags
        # depending on flags either:
        # - 4-byte timestamp + 4-byte size
        # - 8-byte hash

        self.header = pyc_f.read(16)
        if len(self.header) < 16:
            raise ValueError("Header too short")
        if self.header[:4] != importlib.util.MAGIC_NUMBER:
            raise ValueError("Invalid magic")

        # flags is a bitfield:
        # 0x01 - 0 for timestamp invalidation, 1 for hash invalidation
        # 0x02 - checked_source flag (for hash invalidation)
        # other bits are unused and must be zero
        self.flags, = struct.unpack_from("<L", self.header, 4)
        if self.flags & ~0x3:
            raise ValueError("Unexpected bits in flags set")
        self.invalidate_hash = bool(self.flags & 0x01)
        self.checked_source = bool(self.flags & 0x02)

        if self.checked_source and not self.invalidate_hash:
            raise ValueError(
                "checked_source flag set for timestamp invalidation")
        if self.invalidate_hash:
            # hash-based invalidation
            # (Python is passing this hash as a bytestring)
            self.py_hash = self.header[8:16]
            assert len(self.py_hash) == 8
        else:
            # timestamp-based invalidation
            self.py_timestamp, self.py_size = (
                struct.unpack_from("<LL", self.header, 8))


def qa_verify_pyc(destdir: Path, sitedirs: typing.Iterable[Path]):
    missing_pyc = []
    invalid_pyc = []
    mismatched_pyc = []
    stray_pyc = []

    for sitedir in sitedirs:
        top_path = destdir / sitedir.relative_to(sitedir.root)
        if not top_path.is_dir():
            continue

        py_files: typing.Set[Path] = set()
        pyc_files: typing.Set[Path] = set()

        for path, dirs, files in os.walk(top_path):
            for fn in files:
                if fn.endswith(".py"):
                    py_files.add(Path(path) / fn)
                elif fn.endswith((".pyc", ".pyo")):
                    pyc_files.add(Path(path) / fn)

        for py in py_files:
            py_stat = py.stat()

            for opt in ("", 1, 2):
                pyc = Path(
                    importlib.util.cache_from_source(py, optimization=opt))
                # 1. check for missing .pyc files
                if pyc not in pyc_files:
                    missing_pyc.append((pyc, py))
                    continue

                pyc_files.remove(pyc)
                # 2. check the header
                with pyc.open("rb") as f:
                    try:
                        header = PEP552Header(f)
                    except ValueError:
                        invalid_pyc.append((pyc, py))
                        continue

                # 3. check whether .pyc matches the .py file
                if header.invalidate_hash:
                    # NB: even though !checked_source implies that Python
                    # does not verify the .pyc validity, we do because
                    # per that mode we're actually responsible for ensuring
                    # that the file is valid
                    with py.open("rb") as f:
                        py_hash = importlib.util.source_hash(f.read())
                    if py_hash != header.py_hash:
                        mismatched_pyc.append((pyc, py, "hash"))
                else:
                    if int(py_stat.st_mtime) != header.py_timestamp:
                        mismatched_pyc.append((pyc, py, "timestamp"))
                    if py_stat.st_size != header.py_size:
                        mismatched_pyc.append((pyc, py, "size"))

        # 4. any remaining .pyc files are stray
        stray_pyc.extend((pyc,) for pyc in pyc_files)

    return {
        "missing": missing_pyc,
        "invalid": invalid_pyc,
        "mismatched": mismatched_pyc,
        "stray": stray_pyc,
    }
