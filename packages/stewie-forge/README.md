# stewie-forge

STEWIE **FORGE**: the sourced planetary **geotechnics + terramechanics** models the planner and the conserved
authority consume, plus the `PhysicsBackend` interface. Bekker/Wong-Reece pressure-sinkage, Janosi-Hanamoto
slip, the Lyasko low-g reduction, and Terzaghi/Vesic static bearing capacity. Analytical + conserved-first;
a Chrono geometry-oracle backend is an optional `[chrono]` extra and is advisory only (never release authority
while it does not conserve mass). Depends only on the numeric stack (numpy) -- citable + installable on its own.
The body->params conversion (which applies the `stewie.specs.config` overlay) stays in stewie-core, not here.
