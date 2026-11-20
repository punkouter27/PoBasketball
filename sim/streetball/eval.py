"""Profile B standardized evaluation entrypoint alias for streetball.evaluate.

uv run python -m streetball.eval --level l0_stand --ckpt runs/<run>/model.pt [--episodes 200]
"""

from __future__ import annotations

from streetball.evaluate import evaluate, main

__all__ = ["evaluate", "main"]

if __name__ == "__main__":
    main()
