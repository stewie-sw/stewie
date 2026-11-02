//! The model and physics registries (RW-55b13; Python `routers.models`): the Models pane's registry read
//! (operator and above), the physics-backend ledger, the body-by-backend compatibility matrix (operator and above),
//! and the runtime-profile, backend-authority and terramechanics-spine registries (public). Every row is the real
//! registry's, exported by `oracle/export_registries.py` as `model_registries.json`.

use std::sync::{Arc, LazyLock};

use axum::Router;
use axum::extract::{Query, Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::{Map, Value, json};

use crate::admin::require_role;
use crate::app::{AppState, Head, blocking, err};
use crate::validate::{self, Field, Kind, Model};

static REGISTRIES: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/model_registries.json"
    ))
    .unwrap_or(Value::Null)
});

pub(crate) fn reg(key: &str) -> Value {
    REGISTRIES.get(key).cloned().unwrap_or(Value::Null)
}

fn count(v: &Value) -> usize {
    v.as_array().map_or(0, Vec::len)
}

/// The model and configuration registries, and the model-deployment governance (operator and above).
async fn models(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_role(st, &h, "operator")?;
        let (profiles, vehicles, bodies) = (reg("profiles"), reg("vehicles"), reg("bodies"));
        let deployable = profiles
            .as_array()
            .map_or(0, |p| p.iter().filter(|r| r["deployment_ready"] == true).count());
        let governance = json!({
            "contract": "ModelArtifact (stewie.contracts, FS-12/§25.3)",
            "schema_endpoint": "/contracts/schema",
            "deployment_ready_criteria": [
                "dataset_lineage recorded (training-data lineage, RL-01)",
                "eval_split recorded (evaluation lineage, RL-01)",
                "input_schema declared (typed input contract)",
                "output_schema declared (typed estimate contract)",
                "latency_budget_ms > 0",
                "memory_budget_mb > 0",
                "calibrated",
                "ood_detector present",
                "deterministic fallback or rollback_to set",
                "off the rover command path (command_path == False)",
            ],
            "command_path_invariant":
                "no learned model may be on the rover command path (ModelArtifact rejects command_path=True)",
            "command_path_enforced": reg("command_path_enforced"),
            "deployed_models": [],
            "status": "No learned model is deployed on the command path. The ModelArtifact contract + ML-01 \
                       deployment-ready gate are defined (schema at /contracts/schema); a live model registry \
                       (FS-12) is gated and ships no instances on this build.",
        });
        Ok(axum::Json(json!({
            "ok": true,
            "profile_count": count(&profiles), "profiles_deployable": deployable, "profiles": profiles,
            "default_profile": reg("default_profile"),
            "vehicle_count": count(&vehicles), "vehicles": vehicles, "default_vehicle": reg("default_vehicle"),
            "body_count": count(&bodies), "bodies": bodies, "default_body": reg("default_body"),
            "model_governance": governance,
            "note": "Registries are the real source of truth: system profiles (specs/profiles.py, exact-bytes \
                     sha256 + VERIFIED/UNVERIFIED status), the vehicle registry (specs/vehicles.py), and the \
                     body/soil registry (specs/bodies.py), each with provenance. Model governance is the real \
                     ModelArtifact (ML-01) deployment-ready gate + §25.3 no-command-path invariant; no learned \
                     model is deployed on the command path.",
        }))
        .into_response())
    })
    .await
}

/// The selectable physics backends and the model-governance ledger (public).
async fn backends() -> Response {
    let (selectable, models) = (reg("selectable_backends"), reg("physics_models"));
    axum::Json(json!({
        "ok": true,
        "backend_count": count(&selectable), "selectable_backends": selectable,
        "live_default_model": reg("live_default_model"),
        "model_count": count(&models), "models": models,
        "note": "A mission's physics_backend_id selects the terramechanics engine; only conserved, release-authority \
                 backends are selectable (list_backends()). The models ledger is the EG-12 governance record \
                 (validated/frozen/deprecated per version); a not-yet-conserving oracle (tier3_chrono) appears with \
                 validated=False and is excluded from the selectable set.",
    }))
    .into_response()
}

const COMPAT_QUERY: Model = Model {
    fields: &[Field("allow_analog", Kind::Bool { default: false })],
    forbid_extra: false,
};

/// The body-by-backend compatibility matrix, with the analog-soil override (operator and above).
async fn compatibility(
    State(st): State<Arc<AppState>>,
    Query(query): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_role(st, &h, "operator")?;
        let raw = crate::spec_routes::query(&query, COMPAT_QUERY)?;
        let allow_analog = raw.get("allow_analog").and_then(validate::as_bool).unwrap_or(false);
        let backends: Vec<String> = reg("selectable_backends")
            .as_array()
            .map(|a| a.iter().filter_map(|b| b.as_str().map(str::to_owned)).collect())
            .unwrap_or_default();
        let models = reg("physics_models");
        let validated = |be: &str, body: &str| {
            models.as_array().is_some_and(|ms| {
                ms.iter().any(|m| m["backend_id"] == be && m["validated_bodies"].as_array().is_some_and(|v| v.iter().any(|b| b == body)))
            })
        };
        let regime = reg("body_in_regime");
        let regime = regime.as_object().ok_or_else(|| err(StatusCode::INTERNAL_SERVER_ERROR, "no body regimes"))?;
        // the map's keys come sorted, as the Python's `sorted(BODIES)`
        let bodies: Vec<&String> = regime.keys().collect();
        let mut matrix = Map::new();
        for body in &bodies {
            let in_regime = regime[*body] == true;
            let row: Map<String, Value> = backends
                .iter()
                .map(|be| {
                    let cell = match (in_regime, allow_analog, validated(be, body)) {
                        (false, false, _) => json!({"supported": false, "regime_ok": false,
                            "reason": "microgravity: Bekker terramechanics out-of-regime (refused)"}),
                        (false, true, _) => json!({"supported": true, "regime_ok": false,
                            "reason": "microgravity: supported ONLY via explicit gravity-loaded analog soil \
                                       (caveated [UNKNOWN])"}),
                        (true, _, true) => json!({"supported": true, "regime_ok": true,
                            "reason": "gravity-loaded + validated for this backend"}),
                        (true, _, false) => json!({"supported": false, "regime_ok": true,
                            "reason": "gravity-loaded but not validated for this backend"}),
                    };
                    (be.clone(), cell)
                })
                .collect();
            matrix.insert((*body).clone(), Value::Object(row));
        }
        Ok(axum::Json(json!({"ok": true, "allow_analog": allow_analog, "backends": backends, "bodies": bodies,
                             "matrix": matrix}))
        .into_response())
    })
    .await
}

/// The runtime-profile registry (public).
async fn runtime_profiles() -> Response {
    let p = reg("runtime_profiles");
    axum::Json(json!({
        "ok": true, "count": count(&p), "profiles": p,
        "note": "A SIL/twin/replay/sim profile rehearses + produces evidence but holds no live command authority \
                 (can_release/can_execute False); only hil/field_test/live_rover can release/execute on real \
                 hardware, escalating command_capability none->bounded->full.",
    }))
    .into_response()
}

/// The physics backend authority registry (public).
async fn authority() -> Response {
    let b = reg("backend_authority");
    axum::Json(json!({
        "ok": true, "count": count(&b), "backends": b,
        "note": "Every planner/report value must name the backend that produced it. Only tier2_numpy (conserved \
                 terrain) + hardware (real) are release/execute-eligible; gazebo/chrono are rehearsal-only; godot \
                 renders and never owns physics or command authority.",
    }))
    .into_response()
}

/// The terramechanics spine of the conserved solver (public).
async fn spine() -> Response {
    let t = reg("terra_spine");
    axum::Json(json!({
        "ok": true, "backend": "tier2_numpy", "count": count(&t), "terms": t,
        "note": "Each computed term names the real stewie.physics callable that produces it; input terms \
                 (slope/roughness/density) are terrain/body-derived. Calibration status is honest per term \
                 (measured vs calibrated Bekker moduli).",
    }))
    .into_response()
}

/// The model and physics registry routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/models", get(models))
        .route("/physics/backends", get(backends))
        .route("/physics/compatibility", get(compatibility))
        .route("/runtime/profiles", get(runtime_profiles))
        .route("/physics/authority", get(authority))
        .route("/physics/terramechanics-spine", get(spine))
}
