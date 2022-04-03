import argparse
import os
import sys


def get_toml(path):
    import tomli

    try:
        with open(path, "rb") as f:
            return tomli.load(f)
    except FileNotFoundError:
        return {}


def get_backend(args):
    with os.fdopen(args.output_fd, "w") as out:
        print(get_toml(args.pyproject_toml)
              .get("build-system", {})
              .get("build-backend", ""),
              file=out)
    return 0


def main(argv=sys.argv):
    argp = argparse.ArgumentParser(prog=argv[0])

    subp = argp.add_subparsers(dest="command",
                               required=True)

    parser = subp.add_parser("get-backend",
                             help="Print build-backend from pyproject.toml")
    parser.add_argument("--output-fd",
                        help="FD to use for output",
                        required=True,
                        type=int)
    parser.add_argument("--pyproject-toml",
                        default="pyproject.toml",
                        help="Path to pyproject.toml file")

    args = argp.parse_args(argv[1:])

    func = globals()[args.command.replace("-", "_")]
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
