# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import argparse
import contextlib
import json
import logging
import sys
import tempfile
import typing

from pathlib import Path, PurePath

from gpep517.build import build_wheel_impl
from gpep517.install import install_wheel_impl
from gpep517.utils import DEFAULT_PREFIX, get_toml, install_scheme_dict


ALL_OPT_LEVELS = [0, 1, 2]
DEFAULT_FALLBACK_BACKEND = "setuptools.build_meta:__legacy__"


def open_output(fd: int) -> typing.ContextManager[typing.TextIO]:
    """Safely return file open for outputting into fd"""
    if fd == 0:
        raise RuntimeError("--output-fd 0 invalid")
    elif fd == 1:
        return contextlib.nullcontext(sys.stdout)
    elif fd == 2:
        return contextlib.nullcontext(sys.stderr)
    return open(fd, "w")


def get_backend(args):
    with open_output(args.output_fd) as out:
        print(get_toml(args.pyproject_toml)
              .get("build-system", {})
              .get("build-backend", ""),
              file=out)
    return 0


def build_wheel(args):
    with open_output(args.output_fd) as out:
        print(build_wheel_impl(args, args.wheel_dir), file=out)
    return 0


def parse_optimize_arg(val):
    spl = val.split(",")
    if "all" in spl:
        return ALL_OPT_LEVELS
    return [int(x) for x in spl]


def install_wheel(args):
    install_wheel_impl(args, args.wheel)

    return 0


def install_from_source(args):
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        wheel = build_wheel_impl(args, temp_path)
        install_wheel_impl(args, temp_path / wheel)

    return 0


def verify_pyc(args):
    from gpep517.qa import qa_verify_pyc

    install_dict = install_scheme_dict(args.prefix or DEFAULT_PREFIX, "")
    sitedirs = frozenset(Path(install_dict[x]) for x in ("purelib", "platlib"))
    result = qa_verify_pyc(args.destdir, sitedirs)

    def fpath(p):
        if isinstance(p, Path):
            return str(p.root / p.relative_to(args.destdir))
        return p

    for kind, entries in result.items():
        for e in sorted(entries):
            print(f"{kind}:{':'.join(fpath(x) for x in e)}")
    return 1 if any(v for v in result.values()) else 0


def add_prefix_args(parser):
    parser.add_argument("--prefix",
                        type=Path,
                        help="Prefix to install to "
                        f"(default: {DEFAULT_PREFIX})")


def add_install_path_args(parser):
    parser.add_argument("--destdir",
                        type=Path,
                        help="Staging directory for the install (it will "
                        "be prepended to all paths)",
                        required=True)


def add_build_args(parser):
    group = parser.add_argument_group("backend selection")
    group.add_argument("--backend",
                       help="Backend to use (defaults to reading "
                            "from pyproject.toml)")
    group.add_argument("--fallback-backend",
                       default=DEFAULT_FALLBACK_BACKEND,
                       help="Backend to use if pyproject.toml does not exist "
                       "or does not specify one "
                       f"(default: {DEFAULT_FALLBACK_BACKEND!r})")
    group.add_argument("--no-fallback-backend",
                       action="store_const",
                       dest="fallback_backend",
                       const=None,
                       help="Disable backend fallback (i.e. require backend "
                       "declaration in pyproject.toml")
    group.add_argument("--pyproject-toml",
                       type=Path,
                       default="pyproject.toml",
                       help="Path to pyproject.toml file (used only if "
                       "--backend is not specified)")

    group = parser.add_argument_group("build options")
    group.add_argument("--allow-compressed",
                       help="Allow creating compressed zipfiles (gpep517 "
                       "will attempt to patch compression out by default)",
                       action="store_true")
    group.add_argument("--config-json",
                       help="JSON-encoded dictionary of config_settings "
                            "to pass to the build backend",
                       type=json.loads)
    group.add_argument("--sysroot",
                       help="Patch sysconfig paths to use specified sysroot "
                            "(experimental cross-compilation support)",
                       type=Path)


def add_install_args(parser):
    add_install_path_args(parser)

    group = parser.add_argument_group("install options")
    group.add_argument("--interpreter",
                       type=Path,
                       default=sys.executable,
                       help="The interpreter to put in script shebangs "
                       f"(default: {sys.executable})")
    group.add_argument("--optimize",
                       type=parse_optimize_arg,
                       default=[],
                       help="Comma-separated list of optimization levels "
                       "to compile bytecode for (default: none), pass 'all' "
                       "to enable all known optimization levels (currently: "
                       f"{', '.join(str(x) for x in ALL_OPT_LEVELS)})")
    group.add_argument("--overwrite",
                       action="store_true",
                       help="Permit overwriting files in destdir")
    group.add_argument("--symlink-pyc",
                       action="store_true",
                       help="Symlink .pyc files between optimization levels "
                       "if their contents match")

    group.add_argument("--symlink-to",
                       type=PurePath,
                       help="Install symlinks to another directory rather "
                       "than files if they match respective paths "
                       "in the other directory (useful for deduplicating "
                       "packages across Python implementations)")


def main(argv=sys.argv):
    argp = argparse.ArgumentParser(prog=argv[0])
    argp.add_argument("-q", "--quiet",
                      action="store_const",
                      dest="loglevel",
                      const=logging.WARNING,
                      default=logging.INFO,
                      help="Disable verbose progress reporting")

    subp = argp.add_subparsers(dest="command",
                               required=True)

    parser = subp.add_parser("get-backend",
                             help="Print build-backend from pyproject.toml")
    parser.add_argument("--output-fd",
                        default=1,
                        help="FD to use for output (default: 1)",
                        type=int)
    parser.add_argument("--pyproject-toml",
                        type=Path,
                        default="pyproject.toml",
                        help="Path to pyproject.toml file")

    parser = subp.add_parser("build-wheel",
                             help="Build wheel from sources")
    group = parser.add_argument_group("required arguments")
    group.add_argument("--output-fd",
                       help="FD to output the wheel name to",
                       required=True,
                       type=int)
    group.add_argument("--wheel-dir",
                       type=Path,
                       help="Directory to write the wheel into",
                       required=True)
    add_prefix_args(parser)
    add_build_args(parser)

    parser = subp.add_parser("install-from-source",
                             help="Build and install wheel from sources "
                             "(without preserving the wheel)")
    add_prefix_args(parser)
    add_build_args(parser)
    add_install_args(parser)

    parser = subp.add_parser("install-wheel",
                             help="Install the specified wheel")
    add_prefix_args(parser)
    add_install_args(parser)
    parser.add_argument("wheel",
                        type=Path,
                        help="Wheel to install")

    parser = subp.add_parser("verify-pyc",
                             help="Verify that all installed modules were "
                                  "byte-compiled and there are no stray .pyc "
                                  "files")
    add_prefix_args(parser)
    add_install_path_args(parser)

    args = argp.parse_args(argv[1:])
    logging.basicConfig(format="{asctime} {name} {levelname} {message}",
                        style="{",
                        level=args.loglevel)

    func = globals()[args.command.replace("-", "_")]
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
