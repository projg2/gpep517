# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import filecmp
import functools
import os
import typing

from pathlib import Path, PurePath

from gpep517.utils import DEFAULT_PREFIX, install_scheme_dict, logger


def install_wheel_impl(args, wheel: Path):
    from installer import install
    from installer.destinations import SchemeDictionaryDestination
    from installer.records import RecordEntry
    from installer.sources import WheelFile
    from installer.utils import Scheme, get_launcher_kind

    class DeduplicatingDestionation(SchemeDictionaryDestination):
        def __init__(
            self,
            *args,
            overwrite: bool,
            symlink_to: typing.Optional[PurePath],
            **kwargs,
        ) -> None:
            super().__init__(*args, **kwargs)

            self.overwrite = overwrite
            self.symlink_to = symlink_to

            if symlink_to is not None:
                if os.name == "nt":
                    raise RuntimeError(
                        "--symlink-to is not supported on Windows")
                purelib_path = PurePath(self.scheme_dict["purelib"])
                if self.scheme_dict["platlib"] != self.scheme_dict["purelib"]:
                    raise NotImplementedError(
                        "The implementation currently requires that platlib "
                        f"({self.scheme_dict['platlib']!r}) is the same "
                        f"as purelib ({self.scheme_dict['purelib']!r})"
                    )
                self.destdir_purelib = (
                    Path(self.destdir) /
                    purelib_path.relative_to(purelib_path.anchor))

        @functools.cache
        def check_symlink_to(self) -> None:
            full_symlink_to = self.destdir_purelib / self.symlink_to
            if not full_symlink_to.exists():
                raise FileNotFoundError(
                    "--symlink-to references a path that does not exist "
                    f"in --destdir: {full_symlink_to}"
                )

        def write_to_fs(
            self,
            scheme: Scheme,
            path: str,
            stream: typing.BinaryIO,
            is_executable: bool,
        ) -> RecordEntry:
            try:
                ret = super().write_to_fs(scheme, path, stream, is_executable)
            except FileExistsError:
                if not self.overwrite:
                    raise
                relative_path = PurePath(self.scheme_dict[scheme]) / path
                full_path = Path(self.destdir).joinpath(
                    relative_path.relative_to(relative_path.anchor))
                full_path.unlink()
                ret = super().write_to_fs(scheme, path, stream, is_executable)

            if scheme in ("platlib",
                          "purelib") and self.symlink_to is not None:
                path_dir = PurePath(path).parent
                to_top_dir = len(path_dir.parts) * ("..",)
                symlink_target = Path(*to_top_dir) / self.symlink_to / path
                orig_path = self.destdir_purelib / path
                full_target = self.destdir_purelib / self.symlink_to / path
                try:
                    if not filecmp.cmp(orig_path, full_target):
                        return ret
                except FileNotFoundError:
                    self.check_symlink_to()
                else:
                    orig_path.unlink()
                    orig_path.symlink_to(symlink_target)

            return ret

    with WheelFile.open(wheel) as source:
        dest = DeduplicatingDestionation(
            install_scheme_dict(args.prefix or DEFAULT_PREFIX,
                                source.distribution),
            str(args.interpreter),
            get_launcher_kind(),
            bytecode_optimization_levels=args.optimize,
            destdir=str(args.destdir),
            overwrite=args.overwrite,
            symlink_to=args.symlink_to,
        )
        logger.info(f"Installing {wheel} into {args.destdir}")
        install(source, dest, {})
        logger.info("Installation complete")
