"""Capture one complete, scoped DOM observation from the local fixture service."""
import argparse
from ui_common import cli_result, observe, read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    def run():
        path = observe(args.directory)
        return {"status": "observed", "observation": str(path), "record": read(path)}
    return cli_result(run)


if __name__ == "__main__":
    raise SystemExit(main())
