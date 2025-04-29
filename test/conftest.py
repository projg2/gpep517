# (c) 2022-2025 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import io
import sys
import zipfile

import pytest

try:
    import distutils.sysconfig as distutils_sysconfig
except ImportError:
    distutils_sysconfig = None


@pytest.fixture
def verify_mod_cleanup():
    def get_modules():
        # these modules get imported when we query sysconfig
        return sorted(
            x for x in sys.modules
            if not x.startswith("_sysconfigdata") and
            x not in ("_osx_support",)
        )

    orig_modules = get_modules()
    orig_path = list(sys.path)
    yield
    assert orig_path == sys.path
    assert orig_modules == get_modules()


@pytest.fixture
def verify_zipfile_cleanup(tmp_path):
    """Verify that we are reverting zipfile patching correctly"""
    yield
    with open(tmp_path / "write.txt", "wb") as f:
        f.write(b"data")
    with io.BytesIO() as f:
        with zipfile.ZipFile(f, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            with zipf.open("open.txt", "w") as f:
                f.write(b"data")
            zipf.writestr("writestr.txt", b"data")
            zipf.write(tmp_path / "write.txt", "write.txt")
            assert ({zipfile.ZIP_DEFLATED}
                    == {x.compress_type for x in zipf.infolist()})


@pytest.fixture
def distutils_cache_cleanup():
    try:
        yield
    finally:
        if distutils_sysconfig is not None and hasattr(distutils_sysconfig,
                                                       "_config_vars"):
            distutils_sysconfig._config_vars = None
