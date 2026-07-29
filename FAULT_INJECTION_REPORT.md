# Fault-injection report

**Artifact ID:** `ART-FAULT-INJECTION-REPORT`
**Producer node:** `EXP-030`
**Consumers:** `REV-010`, `DISS-010`
**Machine report:** `reports/ultrabuild/fault-injection/fault-injection-report.json`
**Status:** eight of eight implemented controlled probes passed.

The executable probes cover exact duplicate delivery, conflicting idempotency reuse, payload
bit-rot, mutable-head corruption and deterministic rebuild, delayed stale evidence, future
transaction evidence, evaluator-reference poisoning, and equal-support conflicting observations.
Every registered expected outcome was observed.

The report does not cover physical sensor dropout, ROS clock partitions, database process death
during fsync, bandwidth/packet loss, actuator failure, or simulator numerical divergence. Passing
these eight in-process probes is not a safety certification.
