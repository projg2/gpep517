# (c) 2022-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import argparse
import contextlib
import functools
import importlib
import importlib.util
import json
import logging
import os
import pathlib
import sys
import sysconfig
import tempfile
import typing

from pathlib import Path


ALL_OPT_LEVELS = [0, 1, 2]
DEFAULT_PREFIX = Path("/usr")
DEFAULT_FALLBACK_BACKEND = "setuptools.build_meta:__legacy__"

logger = logging.getLogger("gpep517")


def get_toml(path: Path):
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


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


@contextlib.contextmanager
def disable_zip_compression():
    import zipfile
    orig_open = zipfile.ZipFile.open
    orig_write = zipfile.ZipFile.write
    orig_writestr = zipfile.ZipFile.writestr

    @functools.wraps(zipfile.ZipFile.open)
    def override_open(self, name, mode="r", pwd=None,
                      *, force_zip64=False):
        if mode == "w":
            if not isinstance(name, zipfile.ZipInfo):
                name = zipfile.ZipInfo(name)
            name.compress_type = zipfile.ZIP_STORED
        ret = orig_open(self, name, mode, pwd, force_zip64=force_zip64)
        return ret

    @functools.wraps(zipfile.ZipFile.write)
    def override_write(self, filename, arcname=None,
                       compress_type=None, compresslevel=None):
        return orig_write(self, filename, arcname, zipfile.ZIP_STORED)

    @functools.wraps(zipfile.ZipFile.writestr)
    def override_writestr(self, zinfo_or_arcname, data,
                          compress_type=None, compresslevel=None):
        return orig_writestr(self, zinfo_or_arcname, data,
                             zipfile.ZIP_STORED)

    zipfile.ZipFile.open = override_open
    zipfile.ZipFile.write = override_write
    zipfile.ZipFile.writestr = override_writestr

    try:
        yield
    finally:
        zipfile.ZipFile.open = orig_open
        zipfile.ZipFile.write = orig_write
        zipfile.ZipFile.writestr = orig_writestr


@contextlib.contextmanager
def patch_sysconfig(sysroot: Path,
                    prefix: typing.Optional[Path],
                    ):
    get_vars = {}
    if prefix is not None:
        get_vars["installed_base"] = prefix

    stdlib_path = Path(sysconfig.get_path("stdlib", vars=get_vars))
    if not stdlib_path.is_absolute():
        raise RuntimeError(f"stdlib path {stdlib_path} is not absolute")
    sysroot_stdlib = sysroot / stdlib_path.relative_to("/")
    logger.info(f"Searching for sysconfig in {sysroot_stdlib}")
    data_paths = list(sysroot_stdlib.glob("_sysconfigdata_*.py"))
    if len(data_paths) != 1:
        raise RuntimeError(
            f"should have found one _sysconfigdata file, found {data_paths}")
    logger.info(f"Using sysconfig from {data_paths[0]}")

    data_spec = importlib.util.spec_from_file_location(
        "_sysconfig_data", data_paths[0])
    data_mod = importlib.util.module_from_spec(data_spec)
    data_spec.loader.exec_module(data_mod)
    sysroot_vars = data_mod.build_time_vars

    orig_config_vars = sysconfig.get_config_vars
    orig_get_platform = sysconfig.get_platform

    def patched_config_vars():
        cvars = orig_config_vars().copy()

        # path variables: we copy them from sysroot, and prepend sysroot
        for modvar in ("CONFINCLUDEDIR", "CONFINCLUDEPY", "INCLUDEDIR",
                       "INCLUDEPY", "LIBDIR"):
            srcvar = modvar
            if srcvar.startswith("CONF") and srcvar not in sysroot_vars:
                # PyPy does not define CONFINCLUDE*, distutils.sysconfig
                # works around that by hacking the path around manually.
                # However, setting CONFINCLUDE* here disables the hack
                # and gets sane behavior back.
                srcvar = srcvar[4:]
            if srcvar in sysroot_vars:
                sysroot_path = Path(sysroot_vars[srcvar])
                if not sysroot_path.is_absolute():
                    raise RuntimeError(
                        f"{srcvar} path {sysroot_path} is not absolute")
                cvars[modvar] = str(sysroot / sysroot_path.relative_to("/"))

        # ABI-specific variables: plain copy
        for modvar in ("SOABI", "EXT_SUFFIX"):
            if modvar in sysroot_vars:
                cvars[modvar] = sysroot_vars[modvar]

        return cvars

    def patched_get_platform():
        return sysroot_vars["MULTIARCH"]

    sysconfig.get_config_vars = patched_config_vars
    sysconfig.get_platform = patched_get_platform
    try:
        yield
    finally:
        sysconfig.get_config_vars = orig_config_vars
        sysconfig.get_platform = orig_get_platform


@contextlib.contextmanager
def scope_modules():
    orig_modules = frozenset(sys.modules)
    orig_path = list(sys.path)

    try:
        yield
    finally:
        for mod in frozenset(sys.modules).difference(orig_modules):
            del sys.modules[mod]
        sys.path = orig_path


def build_wheel_impl(args, wheel_dir: Path):
    build_sys = get_toml(args.pyproject_toml).get("build-system", {})
    backend_s = args.backend
    if backend_s is None:
        backend_s = build_sys.get("build-backend", args.fallback_backend)
        if backend_s is None:
            raise RuntimeError(
                "pyproject.toml is missing or does not specify build-backend "
                "and --no-fallback-backend specified")
    package, _, obj = backend_s.partition(":")

    zip_ctx = (contextlib.nullcontext if args.allow_compressed
               else disable_zip_compression)

    if args.sysroot is not None:
        sysconfig_ctx = patch_sysconfig(args.sysroot,
                                        args.prefix)
    else:
        sysconfig_ctx = contextlib.nullcontext()

    with zip_ctx(), sysconfig_ctx, scope_modules():
        def safe_samefile(path, cwd):
            try:
                return cwd.samefile(path)
            except Exception:
                return False

        # strip the current directory from sys.path
        cwd = pathlib.Path.cwd()
        sys.path = [x for x in sys.path if not safe_samefile(x, cwd)]
        sys.path[:0] = build_sys.get("backend-path", [])
        backend = importlib.import_module(package)

        if obj:
            for name in obj.split("."):
                backend = getattr(backend, name)

        wheel_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Building wheel via backend {backend_s}")
        wheel_name = backend.build_wheel(str(wheel_dir), args.config_json)
        logger.info(f"The backend produced {wheel_dir / wheel_name}")

        return wheel_name


def build_wheel(args):
    with open_output(args.output_fd) as out:
        print(build_wheel_impl(args, args.wheel_dir), file=out)
    return 0


def install_scheme_dict(prefix: Path, dist_name: str):
    ret = sysconfig.get_paths(vars={"base": str(prefix),
                                    "platbase": str(prefix)})
    # header path hack copied from installer's __main__.py
    ret["headers"] = os.path.join(
        sysconfig.get_path("include", vars={"installed_base": str(prefix)}),
        dist_name)
    # end of copy-paste
    return ret


def parse_optimize_arg(val):
    spl = val.split(",")
    if "all" in spl:
        return ALL_OPT_LEVELS
    return [int(x) for x in spl]


def install_wheel_impl(args, wheel: Path):
    from installer import install
    from installer.destinations import SchemeDictionaryDestination
    from installer.sources import WheelFile
    from installer.utils import get_launcher_kind

    with WheelFile.open(wheel) as source:
        dest = SchemeDictionaryDestination(
            install_scheme_dict(args.prefix or DEFAULT_PREFIX,
                                source.distribution),
            str(args.interpreter),
            get_launcher_kind(),
            bytecode_optimization_levels=args.optimize,
            destdir=str(args.destdir),
        )
        logger.info(f"Installing {wheel} into {args.destdir}")
        install(source, dest, {})
        logger.info("Installation complete")


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
