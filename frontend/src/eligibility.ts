import { useEffect, useState } from "react";

// [REQ:RF-02] the Release/Execute guard. It does NOT re-implement the profile/backend coherence rule -- it
// reads the REAL backend verdict from GET /rc/eligibility (the RS-01 CommandEligibility contract: the
// pre-emission eligibility + the legible refusal reason). Fail-closed: any error / non-2xx -> not eligible.

export interface Eligibility {
  eligible: boolean;
  reason: string;
  profile?: string;
}

export async function fetchEligibility(mission?: string | null): Promise<Eligibility> {
  try {
    const q = mission ? `?mission=${encodeURIComponent(mission)}` : "";
    const res = await fetch(`/rc/eligibility${q}`, { credentials: "same-origin" });
    if (!res.ok) return { eligible: false, reason: `eligibility unavailable (${res.status})` };
    const d = await res.json();
    return { eligible: !!d.eligible, reason: String(d.reason ?? ""), profile: d.profile };
  } catch (e) {
    return { eligible: false, reason: `eligibility check failed: ${String(e)}` };
  }
}

// React hook: fetch the eligibility verdict for the current mission (re-fetched when it changes). While
// loading, treated as NOT eligible (fail-closed), so Release/Execute never flash an allowed state first.
export function useEligibility(mission: string | null): { loading: boolean; verdict: Eligibility } {
  const [loading, setLoading] = useState(true);
  const [verdict, setVerdict] = useState<Eligibility>({ eligible: false, reason: "checking eligibility…" });
  useEffect(() => {
    let live = true;
    setLoading(true);
    fetchEligibility(mission).then((v) => {
      if (live) { setVerdict(v); setLoading(false); }
    });
    return () => { live = false; };
  }, [mission]);
  return { loading, verdict };
}
