import argparse
import importlib
import json
import os
import sys
import sysconfig


def get_toml(path):
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib

    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def get_backend(args):
    with os.fdopen(args.output_fd, "w") as out:
        print(get_toml(args.pyproject_toml)
              .get("build-system", {})
              .get("build-backend", ""),
              file=out)
    return 0


def build_wheel(args):
    build_sys = get_toml(args.pyproject_toml).get("build-system", {})
    backend_s = args.backend or build_sys["build-backend"]
    package, _, obj = backend_s.partition(":")

    if not args.allow_compressed:
        import zipfile
        zipfile.ZipFile.compression = property(
            lambda self: zipfile.ZIP_STORED,
            lambda self, value: None,
            lambda self: None)
        orig_compress_type = zipfile.ZipInfo.compress_type
        zipfile.ZipInfo.compress_type = property(
            lambda self: zipfile.ZIP_STORED,
            lambda self, value: None,
            lambda self: None)

    path_len = len(sys.path)
    sys.path[:0] = build_sys.get("backend-path", [])
    backend = importlib.import_module(package)

    if obj:
        for name in obj.split("."):
            backend = getattr(backend, name)

    wheel_name = backend.build_wheel(args.wheel_dir, args.config_json)
    sys.path[:len(sys.path)-path_len] = []

    if not args.allow_compressed:
        delattr(zipfile.ZipFile, "compression")
        setattr(zipfile.ZipInfo, "compress_type", orig_compress_type)

    with os.fdopen(args.output_fd, "w") as out:
        print(wheel_name, file=out)
    return 0


def install_scheme_dict(prefix, dist_name):
    ret = sysconfig.get_paths(vars={"base": prefix,
                                    "platbase": prefix})
    # header path hack copied from installer's __main__.py
    ret["headers"] = os.path.join(
        sysconfig.get_path("include", vars={"installed_base": prefix}),
        dist_name)
    # end of copy-paste
    return ret


def install_wheel(args):
    from installer import install
    from installer.destinations import SchemeDictionaryDestination
    from installer.sources import WheelFile
    from installer.utils import get_launcher_kind

    with WheelFile.open(args.wheel) as source:
        dest = SchemeDictionaryDestination(
            install_scheme_dict(args.prefix or "/usr", source.distribution),
            args.interpreter,
            get_launcher_kind(),
            bytecode_optimization_levels=[],
            destdir=args.destdir,
        )
        install(source, dest, {})

    return 0


def main(argv=sys.argv):
    argp = argparse.ArgumentParser(prog=argv[0])

    subp = argp.add_subparsers(dest="command",
                               required=True)

    parser = subp.add_parser("get-backend",
                             help="Print build-backend from pyproject.toml")
    parser.add_argument("--output-fd",
                        default=1,
                        help="FD to use for output (default: 1)",
                        type=int)
    parser.add_argument("--pyproject-toml",
                        default="pyproject.toml",
                        help="Path to pyproject.toml file")

    parser = subp.add_parser("build-wheel",
                             help="Build wheel using specified backend")
    parser.add_argument("--backend",
                        help="Backend to use (defaults to reading "
                             "from pyproject.toml")
    parser.add_argument("--config-json",
                        help="JSON-encoded dictionary of config_settings "
                             "to pass to the build backend",
                        type=json.loads)
    parser.add_argument("--allow-compressed",
                        help="Allow creating compressed zipfiles (gpep517 "
                        "will attempt to patch compression out by default)",
                        action="store_true")
    parser.add_argument("--output-fd",
                        help="FD to output the wheel name to",
                        required=True,
                        type=int)
    parser.add_argument("--pyproject-toml",
                        default="pyproject.toml",
                        help="Path to pyproject.toml file")
    parser.add_argument("--wheel-dir",
                        help="Directory to output the wheel into",
                        required=True)

    parser = subp.add_parser("install-wheel",
                             help="Install wheel")
    parser.add_argument("--destdir",
                        help="Directory to install to",
                        required=True)
    parser.add_argument("--interpreter",
                        default=sys.executable,
                        help="The interpreter to put in script shebangs "
                        f"(default: {sys.executable})")
    parser.add_argument("--prefix",
                        default="/usr",
                        help="Prefix to install to (default: /usr)")
    parser.add_argument("wheel",
                        help="Wheel to install")

    args = argp.parse_args(argv[1:])

    func = globals()[args.command.replace("-", "_")]
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
