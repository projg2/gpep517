# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import contextlib
import functools
import importlib
import importlib.util
import os
import sys
import sysconfig
import typing

from pathlib import Path

from gpep517.utils import get_toml, logger


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
        if os.name == "nt":
            raise RuntimeError("--sysroot is not supported on Windows")
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
        cwd = Path.cwd()
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
