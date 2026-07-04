"""[REQ:BD-01] Versioned BodyProfile records for the body registry (PRD §7.A, lane BD).

Wraps each per-planet ``stewie.specs.bodies.Body`` as a strict, frozen, version-stamped
:class:`stewie.contracts.Contract`, so the body/regolith constants become a MIGRATABLE record (a stable
``id`` + inherited ``schema_version`` + provenance) that serializes losslessly for the frontend rewrite's
body-profile seam -- WITHOUT touching the existing ``bodies`` API. Nothing is re-fabricated: every
``BodyProfile`` is DERIVED from the live ``BODIES`` registry (``BodyProfile.from_body``), and ``to_body``
reconstructs the exact original ``Body`` value-for-value (so ``get_body`` / ``params_for_body`` see unchanged
inputs). Additive: ``BODIES`` / ``get_body`` / ``params_for_body`` callers stay byte-identical.
"""
from __future__ import annotations

from stewie.contracts import Contract
from stewie.specs.bodies import BODIES, Body, get_body


class BodyProfile(Contract):
    """A versioned, serializable snapshot of one :class:`~stewie.specs.bodies.Body`.

    Carries a stable registry ``id``, the inherited ``schema_version`` (migratability), and EVERY real field
    of the source ``Body`` (no derived or fabricated values). Frozen + ``extra='forbid'`` from ``Contract``, so
    it round-trips through JSON losslessly and rejects unknown fields at the boundary.
    """

    id: str                                           # canonical registry key (== Body.name today)
    name: str                                         # Body.name (canonical key, lowercase)
    label: str                                        # display name
    g: float                                          # representative surface gravity [m/s^2]
    bekker_regime: str                                # "gravity-loaded" | "microgravity"
    bulk_density: float | None = None                 # surface regolith bulk density [kg/m^3]
    cohesion_pa: float | None = None                  # representative cohesion [Pa]
    friction_deg: float | None = None                 # internal friction angle [deg]
    repose_deg: float | None = None                   # angle of repose [deg]
    bekker: tuple[float, float, float] | None = None  # (k_c [N/m^2], k_phi [N/m^3], n), if sourced
    confidence: str = ""                              # per-field MEASURED/ESTIMATED/UNKNOWN summary
    g_note: str = ""                                  # gravity variation note
    role: str = ""                                    # habitat/mining role + citation
    provenance: str = ""                              # key citations for the soil constants
    ellipsoid_radius_m: float | None = None           # body reference-ellipsoid radius [m]
    crs: str | None = None                            # planetary geographic CRS (IAU_2015:*), NOT WGS84

    @classmethod
    def from_body(cls, body: Body) -> BodyProfile:
        """Project a live ``Body`` into a versioned profile -- a pure copy of the real registry values."""
        return cls(
            id=body.name,
            name=body.name,
            label=body.label,
            g=body.g,
            bekker_regime=body.bekker_regime,
            bulk_density=body.bulk_density,
            cohesion_pa=body.cohesion_pa,
            friction_deg=body.friction_deg,
            repose_deg=body.repose_deg,
            bekker=None
            if body.bekker is None
            else (float(body.bekker[0]), float(body.bekker[1]), float(body.bekker[2])),
            confidence=body.confidence,
            g_note=body.g_note,
            role=body.role,
            provenance=body.provenance,
            ellipsoid_radius_m=body.ellipsoid_radius_m,
            crs=body.crs,
        )

    def to_body(self) -> Body:
        """Reconstruct the source ``Body`` value-for-value (equal to ``BODIES[self.id]``), so any consumer
        (e.g. ``params_for_body``) sees inputs identical to the pre-profile registry."""
        return Body(
            name=self.name,
            label=self.label,
            g=self.g,
            bekker_regime=self.bekker_regime,
            bulk_density=self.bulk_density,
            cohesion_pa=self.cohesion_pa,
            friction_deg=self.friction_deg,
            repose_deg=self.repose_deg,
            bekker=self.bekker,
            confidence=self.confidence,
            g_note=self.g_note,
            role=self.role,
            provenance=self.provenance,
            ellipsoid_radius_m=self.ellipsoid_radius_m,
            crs=self.crs,
        )


#: the body registry projected to versioned profiles -- DERIVED from BODIES (never re-declared constants).
BODY_PROFILES: dict[str, BodyProfile] = {key: BodyProfile.from_body(body) for key, body in BODIES.items()}


def body_profile(name: str | Body) -> BodyProfile:
    """Resolve a body (case-insensitive name, or a ``Body``) to its versioned ``BodyProfile``.

    Built FROM the live ``BODIES`` registry via ``get_body``, so it stays in lock-step with the source
    constants and never carries a stale copy. Raises ``KeyError`` for an unknown body, exactly as ``get_body``
    does (unchanged error contract)."""
    return BodyProfile.from_body(get_body(name))
