# (c) 2022-2024 Michał Górny
# SPDX-License-Identifier: GPL-2.0-or-later

import json
import pathlib
import sysconfig
import zipfile


def build_wheel(wheel_directory,
                config_settings=None,
                metadata_directory=None):
    ver = (config_settings.get("version", 5) if config_settings is not None
           else 1)
    return f"frobnicate-{ver}-py3-none-any.whl"


class top_class:
    class sub_class:
        def build_wheel(wheel_directory,
                        config_settings=None,
                        metadata_directory=None):
            return "frobnicate-3-py3-none-any.whl"

    def build_wheel(wheel_directory,
                    config_settings=None,
                    metadata_directory=None):
        return "frobnicate-2-py3-none-any.whl"


class zip_open_backend:
    def build_wheel(wheel_directory,
                    config_settings=None,
                    metadata_directory=None):
        with zipfile.ZipFile(pathlib.Path(wheel_directory) / "test.zip",
                             "r") as zipf:
            with zipf.open("test.txt", "r") as f:
                wheel_name = f.read().decode().strip()

        with zipfile.ZipFile(pathlib.Path(wheel_directory) / wheel_name, "w",
                             compression=zipfile.ZIP_DEFLATED) as zipf:
            with zipf.open("test.txt", "w") as f:
                f.write(b"test string")

        return wheel_name


class zip_open_zinfo_backend:
    def build_wheel(wheel_directory,
                    config_settings=None,
                    metadata_directory=None):
        with zipfile.ZipFile(pathlib.Path(wheel_directory) / "test.zip",
                             "r") as zipf:
            with zipf.open(zipf.getinfo("test.txt"), "r") as f:
                wheel_name = f.read().decode().strip()

        with zipfile.ZipFile(pathlib.Path(wheel_directory) / wheel_name, "w",
                             compression=zipfile.ZIP_DEFLATED) as zipf:
            zinfo = zipfile.ZipInfo("test.txt")
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            with zipf.open(zinfo, "w") as f:
                f.write(b"test string")

        return wheel_name


class zip_write_backend:
    def build_wheel(wheel_directory,
                    config_settings=None,
                    metadata_directory=None):
        with zipfile.ZipFile(pathlib.Path(wheel_directory) / "test.zip",
                             "r") as zipf:
            wheel_name = zipf.read("test.txt").decode().strip()

        with open(pathlib.Path(wheel_directory) / "test.txt", "w") as f:
            f.write("test string")

        with zipfile.ZipFile(pathlib.Path(wheel_directory) / wheel_name, "w",
                             compression=zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(pathlib.Path(wheel_directory) / "test.txt", "test.txt",
                       compress_type=zipfile.ZIP_DEFLATED)

        return wheel_name


class zip_writestr_backend:
    def build_wheel(wheel_directory,
                    config_settings=None,
                    metadata_directory=None):
        with zipfile.ZipFile(pathlib.Path(wheel_directory) / "test.zip",
                             "r") as zipf:
            wheel_name = zipf.read("test.txt").decode().strip()

        with zipfile.ZipFile(pathlib.Path(wheel_directory) / wheel_name, "w",
                             compression=zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("test.txt", "test string",
                          compress_type=zipfile.ZIP_DEFLATED)

        return wheel_name


class sysroot_backend:
    def build_wheel(wheel_directory,
                    config_settings=None,
                    metadata_directory=None):
        data = {
            k: sysconfig.get_config_var(k)
            for k in ("CONFINCLUDEDIR", "CONFINCLUDEPY",
                      "INCLUDEDIR", "INCLUDEPY",
                      "LIBDIR",
                      "EXT_SUFFIX", "SOABI",
                      )
        }

        data["_platform"] = sysconfig.get_platform()

        # NB: this can be either the stdlib module in Python < 3.12
        # or the hacked-in setuptools._distutils
        try:
            import distutils.sysconfig
        except ImportError:
            pass
        else:
            data["_distutils"] = {
                "get_python_inc(False)":
                    distutils.sysconfig.get_python_inc(False),
                "get_python_inc(True)":
                    distutils.sysconfig.get_python_inc(True),
            }

        with open(pathlib.Path(wheel_directory) / "data.json", "w") as f:
            json.dump(data, f)

        return "data.json"
