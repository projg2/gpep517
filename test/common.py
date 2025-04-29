# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import os


IS_WINDOWS = os.name == "nt"
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""
