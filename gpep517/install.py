# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

from pathlib import Path

from gpep517.utils import DEFAULT_PREFIX, install_scheme_dict, logger


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
