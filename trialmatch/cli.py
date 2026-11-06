from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from trialmatch.agents import DISCLAIMER, TrialMatchOrchestrator
from trialmatch.reporting import save_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an educational TrialMatch prescreen.")
    parser.add_argument("--sample", type=int, help="Use one of the fictional cases in data/synthetic_cases.json.")
    parser.add_argument("--save", action="store_true", help="Ask for coordinator confirmation before saving.")
    args = parser.parse_args()

    if args.sample is not None:
        cases = json.loads(Path("data/synthetic_cases.json").read_text(encoding="utf-8"))
        if not 1 <= args.sample <= len(cases):
            parser.error(f"--sample must be between 1 and {len(cases)}.")
        text = cases[args.sample - 1]["summary"]
        print(f"Fictional training case {args.sample}; no real patient data is used.")
    else:
        print("Do not enter real patient information. Input is read locally and is not logged.")
        text = getpass.getpass("Paste an anonymous summary (input hidden): ")

    report = TrialMatchOrchestrator().run(text)
    print(DISCLAIMER)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(DISCLAIMER)

    if args.save and not report.rejected:
        approval = input("Coordinator: approve local report save? Type YES to confirm: ")
        if approval == "YES":
            path = save_report(report, approved=True)
            print(f"Saved locally: {path}")
        else:
            print("Coordinator approval was not given; the report was not saved.")


if __name__ == "__main__":
    main()
