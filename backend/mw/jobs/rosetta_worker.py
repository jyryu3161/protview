"""No direct Rosetta worker exists in the selected MVP.

The previous scaffold accepted arbitrary JSON on argv and claimed unfinished protocols.
Production dispatch is intentionally absent until an engine, implementation, and
scientific validation are registered separately. The queue's fixed guardian only
allows its internal lifecycle fixture in tests; it does not import this module.
"""
from __future__ import annotations


def main() -> None:
    raise SystemExit("no validated production Rosetta protocol is installed")


if __name__ == "__main__":
    main()
