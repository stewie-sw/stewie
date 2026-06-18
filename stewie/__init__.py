"""STEWIE platform package. Importing registers the Stewie/* Gymnasium envs (gym-optional no-op)."""
from stewie.envs.registration import register_envs as _register_envs

# PO-13: the single exported version (SemVer; kept in lockstep with pyproject [project].version by
# test_version.py). 0.x = pre-release -- a trainer/simulator surface, not a production release.
__version__ = "0.1.0"

_register_envs()
