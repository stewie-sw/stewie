import { useEffect, useState } from "react";

// [REQ:RF-03] the per-pane fixture-state convention: every data-bound pane resolves to exactly one of
// loading / error / empty / ready, so each migrated pane ships deterministic empty/error/loading/mobile
// states (and a Playwright parity test asserts them) before it flips. Fail-safe: a non-2xx or thrown fetch
// is `error` (e.g. /world 401 for a guest), never a blank pane.
export type ResourceState<T> =
  | { status: "loading" }
  | { status: "error"; error: string }
  | { status: "empty" }
  | { status: "ready"; data: T };

export function useResource<T>(path: string, isEmpty?: (d: T) => boolean): ResourceState<T> {
  const [state, setState] = useState<ResourceState<T>>({ status: "loading" });
  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    fetch(path, { credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return (await r.json()) as T;
      })
      .then((d) => {
        if (live) setState(isEmpty?.(d) ? { status: "empty" } : { status: "ready", data: d });
      })
      .catch((e: unknown) => {
        if (live) setState({ status: "error", error: e instanceof Error ? e.message : String(e) });
      });
    return () => { live = false; };
  }, [path]);
  return state;
}
