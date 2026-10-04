"""Developer CLI: python -m app.pull_coach.replay <manifest>."""
import argparse
from pathlib import Path

from .runner import ReplayRunner, ReplaySpeed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Replay a saved Warcraft Logs snapshot offline")
    parser.add_argument("manifest")
    parser.add_argument("--speed", choices=[mode.value for mode in ReplaySpeed], default="max")
    parser.add_argument("--through-pull", type=int)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    parser.add_argument("--output")
    parser.add_argument("--baseline")
    parser.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)
    step = (lambda: input("Press Enter to replay the next pull (Ctrl-C to stop)...")) \
        if args.speed == ReplaySpeed.STEP.value else None
    result = ReplayRunner().run(args.manifest, args.through_pull, args.baseline,
                                args.update_baseline, ReplaySpeed(args.speed), on_step=step)
    output = result.canonical_json() + "\n" if args.format == "json" else result.human() + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 1 if result.baseline_status == "changed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
