import pathlib
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


class zip_backend:
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
