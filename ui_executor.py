"""Execute one existing, fresh permit. No inference, retry, or replanning."""
import argparse
from ui_common import cli_result, record_path, rpc


def execute(directory, permit):
    path = record_path(directory, permit)
    return rpc(directory, "execute", {"permit": path.name})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--permit", required=True)
    args = parser.parse_args()
    return cli_result(lambda: execute(args.directory, args.permit))


if __name__ == "__main__":
    raise SystemExit(main())
