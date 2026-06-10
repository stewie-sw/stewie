"""STEWIE platform package. Importing registers the Stewie/* Gymnasium envs (gym-optional no-op)."""
from stewie.envs.registration import register_envs as _register_envs

_register_envs()
