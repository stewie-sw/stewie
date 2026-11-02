//! The world-state authority (RW-55b3c; Python `stewie.server.world_state.WorldStateService`): the latest-known
//! identity of each world-state source (the conserved-authority sha, the plan, the belief, the mission stamp)
//! and one durable hash-chained `WorldTransaction` committed for every meaningful transition, the sources a
//! transition does not touch carried forward. The observed twin's identity is read live: the twin a resync
//! mutated when the caller names it (SR-18), else the default twin.

use std::path::Path;
use std::sync::Mutex;

use serde_json::{Map, Value, json};
use stewie_twin::twin_store::TwinStore;
use stewie_twin::world_log::{Snapshot, TransactionLog, WorldTransaction};

use crate::state::{DEFAULT_TWIN_SITE, DEFAULT_TWIN_SOURCE, Terrain};

/// Stamp fields a transition may update (left `None`, carried forward).
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Stamp<'a> {
    pub mission: Option<&'a str>,
    pub site: Option<&'a str>,
    pub body: Option<&'a str>,
    pub mission_t_s: Option<f64>,
}

#[derive(Debug)]
struct Inner {
    log: TransactionLog,
    authority_sha: String,
    plan_id: String,
    belief: Map<String, Value>,
    mission: String,
    site: String,
    body: String,
    mission_t_s: f64,
    /// Where each committed transaction is projected (PG-01), when a database is configured.
    sink: Option<tokio::sync::mpsc::UnboundedSender<Value>>,
}

/// One linked world-state authority; every transition takes its lock, so read-modify-commit never interleaves.
#[derive(Debug)]
pub struct WorldState {
    inner: Mutex<Inner>,
}

impl WorldState {
    /// The authority over `journal` (cold-restored when it exists), its identities re-seeded from the latest
    /// record so the next commit carries them forward.
    ///
    /// # Errors
    /// A journal that does not replay.
    pub fn open(journal: &Path) -> Result<Self, String> {
        let log = TransactionLog::from_journal(journal).map_err(|e| e.to_string())?;
        let mut inner = Inner {
            authority_sha: "genesis".to_owned(),
            plan_id: "none".to_owned(),
            belief: Map::new(),
            mission: "none".to_owned(),
            site: DEFAULT_TWIN_SITE.to_owned(),
            body: "moon".to_owned(),
            mission_t_s: 0.0,
            sink: None,
            log,
        };
        if let Some(t) = inner.log.latest().cloned() {
            inner.authority_sha = t.authority_sha;
            inner.plan_id = t.plan_id;
            inner.belief = t.belief;
            inner.mission = t.mission;
            inner.site = t.site;
            inner.body = t.body;
            inner.mission_t_s = t.mission_t_s;
        }
        Ok(Self {
            inner: Mutex::new(inner),
        })
    }

    /// Project every transaction committed from now on to `sink` (Python's `projection_sink`): its linked body
    /// with the chain hash, as the Python mirrors it.
    pub fn project_to(&self, sink: tokio::sync::mpsc::UnboundedSender<Value>) {
        self.lock().sink = Some(sink);
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Inner> {
        self.inner
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// Commit one linked snapshot of the current identities and the twin's (caller holds the lock). With no
    /// `twin` this locks the default twin itself, so a caller holding the default twin's lock must pass it (as
    /// the resync route does): the twin locks are not re-entrant.
    fn commit(
        inner: &mut Inner,
        terrain: &Terrain,
        provenance: &str,
        stamp: &Stamp<'_>,
        uncertainty_m: f64,
        twin: Option<&TwinStore>,
    ) -> Result<WorldTransaction, String> {
        if let Some(m) = stamp.mission {
            m.clone_into(&mut inner.mission);
        }
        if let Some(s) = stamp.site {
            s.clone_into(&mut inner.site);
        }
        if let Some(b) = stamp.body {
            b.clone_into(&mut inner.body);
        }
        if let Some(t) = stamp.mission_t_s {
            inner.mission_t_s = t;
        }
        let (version, hash) = match twin {
            Some(t) => t.identity(),
            None => terrain
                .twin(DEFAULT_TWIN_SITE, DEFAULT_TWIN_SOURCE)?
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .identity(),
        };
        let snap = Snapshot {
            authority_sha: inner.authority_sha.clone(),
            twin_version: i64::try_from(version).map_err(|e| e.to_string())?,
            twin_hash: hash,
            plan_id: inner.plan_id.clone(),
            belief: inner.belief.clone(),
            mission: inner.mission.clone(),
            site: inner.site.clone(),
            body: inner.body.clone(),
            mission_t_s: inner.mission_t_s,
            provenance: provenance.to_owned(),
            uncertainty_m,
            packet_sha: String::new(),
            vehicle_sha: String::new(),
        };
        let txn = inner.log.commit(snap).cloned().map_err(|e| e.to_string())?;
        if let Some(sink) = &inner.sink {
            let mut body = txn.linked_body();
            body["chain_hash"] = json!(txn.chain_hash);
            // a closed channel only means the projection stopped; the journal already holds the commit
            let _ = sink.send(body);
        }
        Ok(txn)
    }

    /// A new plan was accepted.
    ///
    /// # Errors
    /// Empty provenance, a twin that cannot be read, or a journal write failure.
    pub fn record_plan(
        &self,
        terrain: &Terrain,
        plan_id: &str,
        provenance: &str,
        stamp: &Stamp<'_>,
    ) -> Result<WorldTransaction, String> {
        let mut g = self.lock();
        // set before the commit, as the Python does: a refused commit still moves the plan identity
        plan_id.clone_into(&mut g.plan_id);
        Self::commit(&mut g, terrain, provenance, stamp, 0.0, None)
    }

    /// A conserved terrain change was recorded.
    ///
    /// # Errors
    /// As [`WorldState::record_plan`].
    pub fn record_terrain(
        &self,
        terrain: &Terrain,
        authority_sha: &str,
        provenance: &str,
        stamp: &Stamp<'_>,
    ) -> Result<WorldTransaction, String> {
        let mut g = self.lock();
        authority_sha.clone_into(&mut g.authority_sha);
        Self::commit(&mut g, terrain, provenance, stamp, 0.0, None)
    }

    /// An observed twin advanced; `twin` is the store the caller mutated (SR-18), else the default twin.
    ///
    /// # Errors
    /// As [`WorldState::record_plan`].
    pub fn record_resync(
        &self,
        terrain: &Terrain,
        provenance: &str,
        site: Option<&str>,
        uncertainty_m: f64,
        twin: Option<&TwinStore>,
    ) -> Result<WorldTransaction, String> {
        let mut g = self.lock();
        Self::commit(
            &mut g,
            terrain,
            provenance,
            &Stamp {
                site,
                ..Stamp::default()
            },
            uncertainty_m,
            twin,
        )
    }

    /// The autonomy belief was updated.
    ///
    /// # Errors
    /// As [`WorldState::record_plan`].
    pub fn record_belief(
        &self,
        terrain: &Terrain,
        belief: Map<String, Value>,
        provenance: &str,
        mission_t_s: Option<f64>,
    ) -> Result<WorldTransaction, String> {
        let mut g = self.lock();
        g.belief = belief;
        Self::commit(
            &mut g,
            terrain,
            provenance,
            &Stamp {
                mission_t_s,
                ..Stamp::default()
            },
            0.0,
            None,
        )
    }

    /// A SIM or live execution event, optionally moving the conserved-authority identity and the belief.
    ///
    /// # Errors
    /// As [`WorldState::record_plan`].
    pub fn record_execution_event(
        &self,
        terrain: &Terrain,
        provenance: &str,
        authority_sha: Option<&str>,
        belief: Option<Map<String, Value>>,
        stamp: &Stamp<'_>,
        uncertainty_m: f64,
    ) -> Result<WorldTransaction, String> {
        let mut g = self.lock();
        if let Some(a) = authority_sha {
            a.clone_into(&mut g.authority_sha);
        }
        if let Some(b) = belief {
            g.belief = b;
        }
        Self::commit(&mut g, terrain, provenance, stamp, uncertainty_m, None)
    }

    /// The most recent linked record.
    #[must_use]
    pub fn latest(&self) -> Option<WorldTransaction> {
        self.lock().log.latest().cloned()
    }

    #[must_use]
    pub fn transaction_count(&self) -> usize {
        self.lock().log.transactions().len()
    }

    /// The last `limit` transactions, oldest first, as the timeline the cockpit renders.
    #[must_use]
    pub fn recent(&self, limit: usize) -> Vec<Value> {
        let g = self.lock();
        let all = g.log.transactions();
        all[all.len().saturating_sub(limit)..]
            .iter()
            .map(|t| {
                json!({"seq": t.seq, "provenance": t.provenance, "world_sha": t.world_sha,
                       "twin_version": t.twin_version, "plan_id": t.plan_id, "authority_sha": t.authority_sha,
                       "mission": t.mission, "mission_t_s": t.mission_t_s})
            })
            .collect()
    }

    #[must_use]
    pub fn verify_chain(&self) -> bool {
        self.lock().log.verify_chain()
    }
}
