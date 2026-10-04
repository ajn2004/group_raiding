"""Developer CLI for reviewing and promoting discovered mechanics."""

import argparse
import json
import os
from dataclasses import fields

from app.pull_coach.mechanics.store import DirectoryMechanicsStore
from app.pull_coach.mechanics.verification import MechanicVerificationService, VerifiedMechanicInput


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="pull-coach mechanics")
    parser.add_argument("--root", default=os.getenv("PULL_COACH_MECHANICS_ROOT"), required=os.getenv("PULL_COACH_MECHANICS_ROOT") is None)
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review"); review.add_argument("encounter_id"); review.add_argument("candidate_id")
    reject = commands.add_parser("reject"); reject.add_argument("encounter_id"); reject.add_argument("candidate_id"); reject.add_argument("--reviewer", required=True); reject.add_argument("--reason")
    promote = commands.add_parser("promote"); promote.add_argument("encounter_id"); promote.add_argument("candidate_id")
    promote.add_argument("--input", required=True, help="JSON file containing every VerifiedMechanicInput field")
    promote.add_argument("--replace", action="store_true")
    args = parser.parse_args(argv)
    service = MechanicVerificationService(DirectoryMechanicsStore(args.root))
    if args.command == "review":
        print(json.dumps(service.review(args.encounter_id, args.candidate_id), indent=2, sort_keys=True))
    elif args.command == "reject":
        print(service.reject(args.encounter_id, args.candidate_id, args.reviewer, args.reason))
    else:
        values = json.loads(open(args.input, encoding="utf-8").read())
        allowed = {field.name for field in fields(VerifiedMechanicInput)}
        unknown = set(values) - allowed
        if unknown:
            parser.error(f"unknown verification input fields: {sorted(unknown)}")
        print(service.promote(args.encounter_id, args.candidate_id, VerifiedMechanicInput(**values), replace=args.replace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
