"""Check all task postconditions on a fresh observation; never execute an action."""
import argparse
from ui_common import checks, cli_result, load, observe, read, save_record


def verify(directory):
    directory, _, task = load(directory)
    observation = observe(directory)
    result = checks(read(observation)["value"]["snapshot"], task)
    value = {"status": "completed" if all(result.values()) else "verification_failed",
             "checks": result, "observation": str(observation)}
    path = save_record(directory, "Verification", value)
    return {**value, "verification": str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    value = None
    def run():
        nonlocal value
        value = verify(args.directory)
        return value
    code = cli_result(run)
    return code or (0 if value["status"] == "completed" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
