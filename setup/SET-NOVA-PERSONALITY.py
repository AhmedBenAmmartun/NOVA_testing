from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT = Path(r"C:\Projects\AI Agent")
CONFIG = PROJECT / "config" / "nova_personality.json"

MODES = ("best_friend", "chill", "focus", "professional")
LEVELS = ("low", "medium", "high")
PROFANITY = ("off", "light", "natural", "unfiltered")
EMOJI = ("off", "light", "normal")


def main() -> None:
    parser = argparse.ArgumentParser(description="Change NOVA conversation personality settings.")
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--humor", choices=LEVELS)
    parser.add_argument("--sarcasm", choices=LEVELS)
    parser.add_argument("--profanity", choices=PROFANITY)
    parser.add_argument("--emoji", choices=EMOJI)

    teasing = parser.add_mutually_exclusive_group()
    teasing.add_argument("--teasing", dest="teasing", action="store_true")
    teasing.add_argument("--no-teasing", dest="teasing", action="store_false")
    parser.set_defaults(teasing=None)

    serious = parser.add_mutually_exclusive_group()
    serious.add_argument("--auto-tone-down", dest="auto_tone_down_serious", action="store_true")
    serious.add_argument("--no-auto-tone-down", dest="auto_tone_down_serious", action="store_false")
    parser.set_defaults(auto_tone_down_serious=None)

    args = parser.parse_args()
    data = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.is_file() else {}

    updates = {
        "mode": args.mode,
        "humor": args.humor,
        "sarcasm": args.sarcasm,
        "teasing": args.teasing,
        "profanity": args.profanity,
        "emoji": args.emoji,
        "auto_tone_down_serious": args.auto_tone_down_serious,
    }

    changed = False
    for key, value in updates.items():
        if value is not None:
            data[key] = value
            changed = True

    if not changed:
        print(json.dumps(data, indent=2))
        return

    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("PASS: NOVA personality updated")
    print(json.dumps(data, indent=2))
    print()
    print("Restart NOVA for the new personality settings to take effect.")


if __name__ == "__main__":
    main()
