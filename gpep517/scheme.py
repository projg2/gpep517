# SPDX-FileCopyrightText: Copyright (c) 2020 Pradyun Gedam
# SPDX-License-Identifier: MIT

# Most of this file is copied from https://github.com/pypa/installer/
# with minor tweaks where classes don't have hooks to control their
# internals.

from __future__ import annotations

import contextlib
import io
import os
import shlex
import zipfile
import typing as T

from installer.destinations import SchemeDictionaryDestination
from installer.scripts import Script
from installer.utils import Scheme

if T.TYPE_CHECKING:
    from installer.records import RecordEntry
    from installer.scripts import LauncherKind, ScriptSection

# Borrowed from https://github.com/python/cpython/blob/v3.9.1/Lib/shutil.py#L52
_WINDOWS = os.name == "nt"
_COPY_BUFSIZE = 1024 * 1024 if _WINDOWS else 64 * 1024

_SCRIPT_TEMPLATE = '''
# -*- coding: utf-8 -*-
import re
import sys
from {module} import {import_name}
if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])
    sys.exit({func_path}())
'''


def build_shebang(executable: str, forlauncher: bool,
                  post_interp: str = '') -> bytes:
    """Copy of installer.scripts.build_shebang, that supports overriding flags.

    Basically revert some exclusions from the original distlib code.
    """
    post_interp_ = ' ' + post_interp.lstrip() if post_interp else ''

    if forlauncher:
        simple = True
    else:
        # some systems support more than 127 but 127 is what is portable
        #  - https://www.in-ulm.de/~mascheck/various/shebang/#length
        length = len(executable) + len(post_interp_) + 3
        simple = ' ' not in executable and length <= 127

    if forlauncher or simple:
        shebang = '#!' + executable + post_interp_
    else:
        quoted = shlex.quote(executable)
        # Shebang support for an executable with a space in it is
        # under-specified and platform-dependent, so we use a clever hack to
        # generate a script to run in ``/bin/sh`` that should work on all
        # reasonably modern platforms.
        shebang = '#!/bin/sh\n'

        # This is polyglot code, that is valid sh to re-exec the file with a
        # new command interpreter, but also a python triple-quoted comment
        # string. Since shell only supports single/double quotes, the sequence
        # '''exec' ...... '''  can comment out code. The "exec" command has
        # unnecessary but syntactically valid sh command quoting. All lines
        # after the exec line are not parsed.
        shebang += f"'''exec' {quoted}{post_interp_}" + ' "$0" "$@"\n'
        shebang += "'''"
    return shebang.encode('utf-8')


@contextlib.contextmanager
def fix_shebang(stream: T.BinaryIO, interpreter: str,
                flags: str = '') -> T.Iterator[T.BinaryIO]:
    """Copy of installer.utils.fix_shebang, that supports overriding flags."""

    if flags:
        flags = f' {flags}'

    stream.seek(0)
    if stream.read(8) == b'#!python':
        new_stream = io.BytesIO()
        # write our new shebang
        # gpep517: use build_shebang
        new_stream.write(build_shebang(interpreter, False, flags) + b'\n')
        # copy the rest of the stream
        stream.seek(0)
        stream.readline()  # skip first line
        while True:
            buf = stream.read(_COPY_BUFSIZE)
            if not buf:
                break
            new_stream.write(buf)
        new_stream.seek(0)
        yield new_stream
        new_stream.close()
    else:
        stream.seek(0)
        yield stream


class Gpep517Script(Script):
    def generate(self, executable: str, kind: LauncherKind,
                 flags: str = '') -> T.Tuple[str, bytes]:
        """Generate the executable for the script

        Either a python script or a win32 launcher exe with a python
        script embedded as a zipapp.
        """
        # XXX: undocumented self._get_launcher_data
        launcher = self._get_launcher_data(kind)
        shebang = build_shebang(executable, bool(launcher), flags)
        code = _SCRIPT_TEMPLATE.format(
            module=self.module,
            import_name=self.attr.split('.')[0],
            func_path=self.attr
        ).encode('utf-8')

        if launcher is None:
            return (self.name, shebang + b'\n' + code)

        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as zf:
            zf.writestr('__main__.py', code)
            name = f'{self.name}.exe'
            data = launcher + shebang + b'\n' + stream.getvalue()
            return (name, data)


class Gpep517WheelDestination(SchemeDictionaryDestination):
    def __init__(self, *args, script_flags='', **kwargs):
        super().__init__(*args, **kwargs)
        self.script_flags = script_flags

    def write_file(self, scheme: Scheme, path: T.Union[str, os.PathLike[str]],
                   stream: T.BinaryIO, is_executable: bool) -> RecordEntry:
        spath = os.fspath(path)

        if scheme == 'scripts':
            with fix_shebang(stream, self.interpreter, self.script_flags) as s:
                return self.write_to_fs(scheme, spath, s, is_executable)
        return self.write_to_fs(scheme, spath, stream, is_executable)

    def write_script(self, name: str, module: str, attr: str,
                     section: ScriptSection) -> RecordEntry:
        script = Gpep517Script(name, module, attr, section)
        script_name, data = script.generate(self.interpreter, self.script_kind,
                                            self.script_flags)

        with io.BytesIO(data) as stream:
            scheme = Scheme('scripts')
            entry = self.write_to_fs(scheme, script_name, stream, True)

            # XXX: undocumented self._path_with_destdir
            path = self._path_with_destdir(Scheme('scripts'), script_name)
            mode = os.stat(path).st_mode
            mode |= (mode & 0o444) >> 2
            os.chmod(path, mode)

            return entry
