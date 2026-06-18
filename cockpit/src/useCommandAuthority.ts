/* FS-17: single command authority. The production operator flow is ONE cockpit window; any second window
 * is read-only and cannot emit rover commands. One window claims authority in localStorage with a heartbeat;
 * a window that finds a FRESH claim from another window goes read-only. `storage` + a BroadcastChannel keep
 * windows in sync; localStorage is the durable arbiter. Promotion is EXPLICIT (takeover), never silent.
 * Ported from the vanilla cockpit.js CMD_AUTH; sets body.dataset.cmdrole = owner|readonly. */
import { useCallback, useEffect, useRef, useState } from "react";

const KEY = "stewie_cmd_authority";
const CHANNEL = "stewie_cmd_authority";
const HEARTBEAT_MS = 2000;
const STALE_MS = 6000; // a claim older than ~3 missed heartbeats is stale and may be reclaimed

interface Claim {
  id: string;
  ts: number;
}

function readClaim(): Claim | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}
function fresh(c: Claim | null): boolean {
  return !!c && Date.now() - c.ts < STALE_MS;
}

export interface CommandAuthority {
  isOwner: boolean;
  takeover: () => void;
}

export function useCommandAuthority(): CommandAuthority {
  const idRef = useRef(Math.random().toString(36).slice(2) + Date.now().toString(36));
  const ownerRef = useRef(false);
  const bcRef = useRef<BroadcastChannel | null>(null);
  const [isOwner, setIsOwner] = useState(false);

  const write = useCallback(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify({ id: idRef.current, ts: Date.now() }));
    } catch {
      /* storage unavailable -> stay read-only */
    }
  }, []);

  const apply = useCallback((owner: boolean) => {
    ownerRef.current = owner;
    setIsOwner(owner);
    if (typeof document !== "undefined" && document.body) {
      document.body.dataset.cmdrole = owner ? "owner" : "readonly";
    }
  }, []);

  const evaluate = useCallback(() => {
    const c = readClaim();
    if (fresh(c) && c!.id !== idRef.current) {
      apply(false); // another window holds a fresh claim -> read-only
      return;
    }
    write(); // no fresh claim (or it's ours) -> claim/refresh it
    const after = readClaim();
    apply(!!after && after.id === idRef.current);
  }, [apply, write]);

  const takeover = useCallback(() => {
    write();
    bcRef.current?.postMessage({ t: "takeover", id: idRef.current });
    evaluate();
  }, [evaluate, write]);

  useEffect(() => {
    evaluate();
    const hb = window.setInterval(() => (ownerRef.current ? write() : evaluate()), HEARTBEAT_MS);
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) evaluate();
    };
    window.addEventListener("storage", onStorage);
    try {
      bcRef.current = new BroadcastChannel(CHANNEL);
      bcRef.current.onmessage = () => evaluate();
    } catch {
      bcRef.current = null;
    }
    const onUnload = () => {
      if (ownerRef.current) {
        try {
          localStorage.removeItem(KEY);
        } catch {
          /* ignore */
        }
        bcRef.current?.postMessage({ t: "release", id: idRef.current });
      }
    };
    window.addEventListener("beforeunload", onUnload);
    return () => {
      window.clearInterval(hb);
      window.removeEventListener("storage", onStorage);
      window.removeEventListener("beforeunload", onUnload);
      bcRef.current?.close();
    };
  }, [evaluate, write]);

  return { isOwner, takeover };
}
