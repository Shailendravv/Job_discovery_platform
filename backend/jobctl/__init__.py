"""jobctl — the single CLI entry point the agent drives (PLAN.md §3).

Every command should support ``--json`` for machine-readable output, since
this is what a Claude Code session (not a human) reads in later milestones.
"""
