"""[REQ:GW-04] Asset Library router (ARCH-3): browse / search / inspect / export / recover the durable
assets, SEPARATE from the visible map layers. The reads are PUBLIC map-data reads (like /world/layer-
catalog + /world/layer-manifest) so the keyless public /ide/ can render the library; the recover MUTATION
is operator-gated (it restores shared/live state) and audit-logged. Reuses the existing persistence via
server.asset_library -- no new store. Auth from server.deps; audit from server.services (no app import)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response

from stewie.server import asset_library as AL
from stewie.server.deps import require_role
from stewie.server.services import log_event

router = APIRouter()


@router.get("/library")
def library_list(q: str | None = None, type: str | None = None, include_trash: bool = False):
    """Browse (+ optional ``q`` search / ``type`` filter) the durable assets. Public map-data read: the
    manifest metadata + provenance, NOT the sensitive payloads (mission orders / report bytes stay auth-
    gated). ``include_trash=1`` also returns the recoverable soft-deleted assets."""
    assets = AL.list_assets(q=q, atype=type)
    body: dict = {"ok": True, "assets": assets, "counts": AL.counts(assets), "total": len(assets),
                  "types": list(AL.ASSET_TYPES)}
    if include_trash:
        trash = AL.trash_assets()
        if q:
            trash = [t for t in trash if q.lower() in (str(t.get("id", "")) + " " + t.get("type", "")).lower()]
        body["trash"] = trash
    return body


@router.get("/library/{atype}/{aid}")
def library_inspect(atype: str, aid: str):
    """Inspect ONE durable asset: its manifest record + safe type-specific detail + provenance. Public."""
    rec = AL.get_asset(atype, aid)
    if rec is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no {atype} asset {aid!r}"})
    return {"ok": True, "asset": rec}


@router.get("/library/{atype}/{aid}/export")
def library_export(atype: str, aid: str):
    """Export the durable asset's descriptor as a JSON attachment (the provenance record). The heavy
    payload (report PDF / mission orders) is referenced by the record's auth-gated ``payload_href``,
    never inlined. Public map-data read."""
    rec = AL.export_record(atype, aid)
    if rec is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no {atype} asset {aid!r}"})
    fname = f"stewie_{atype}_{aid}.json".replace("/", "_")
    return Response(content=json.dumps(rec, indent=2, sort_keys=True, default=str),
                    media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.post("/library/{atype}/{aid}/recover")
def library_recover(atype: str, aid: str, identity: str = Depends(require_role("operator"))):
    """Recover (restore) a soft-deleted durable asset from its .trash, in place. Operator+ (it restores
    shared/live state). Reuses server.objects.restore for missions/structures; a report/twin reports the
    honest recovery path rather than pretending. Audit-logged."""
    out = AL.recover_asset(atype, aid)
    if out.get("restored"):
        log_event(identity, "asset.recover", f"{atype}:{aid}")
    return out
