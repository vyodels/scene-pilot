#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a recruiting skill python_inline stub.")
    parser.add_argument("--skill-name", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--status", default="completed")
    args = parser.parse_args()

    payload = {
        "body": {
            "summary": args.summary,
            "checklist": [],
            "anti_patterns": [],
            "artifacts": {
                "python_inline": {
                    "entrypoint": "run",
                    "code": (
                        "def run(payload, context):\n"
                        "    return {\n"
                        f"        'status': '{args.status}',\n"
                        "        'skill': context['skill_id'],\n"
                        "        'payload': payload,\n"
                        "    }\n"
                    ),
                    "input_contract": {},
                    "output_contract": {},
                }
            },
        },
        "execution_hints": {
            "executor_mode": "python_inline",
        },
        "skill_metadata": {
            "creator_standard": "skill-creator",
            "recommended_skill_name": args.skill_name,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
