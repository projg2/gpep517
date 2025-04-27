# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import logging
import os.path
import sys
import sysconfig

from pathlib import Path


DEFAULT_PREFIX = Path("/usr")

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


def install_scheme_dict(prefix: Path, dist_name: str):
    ret = sysconfig.get_paths(vars={"base": str(prefix),
                                    "platbase": str(prefix)})
    # header path hack copied from installer's __main__.py
    ret["headers"] = os.path.join(
        sysconfig.get_path("include", vars={"installed_base": str(prefix)}),
        dist_name)
    # end of copy-paste
    return ret
