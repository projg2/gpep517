def build_wheel(wheel_directory,
                config_settings=None,
                metadata_directory=None):
    return "frobnicate-1-py3-none-any.whl"


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
