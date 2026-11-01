import Feature from "ol/Feature";
import OlMap from "ol/Map";
import View from "ol/View";
import Point from "ol/geom/Point";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import VectorSource from "ol/source/Vector";
import XYZ from "ol/source/XYZ";
import TileGrid from "ol/tilegrid/TileGrid";
import { useEffect, useRef, useState } from "react";
import type { SiteCatalog } from "../contracts/site";
import {
  type Crumb,
  DISPLAY_ROOT,
  type DisplayIndex,
  type Identified,
  addBreadcrumb,
  displayGrid,
  identify,
  sitePins,
} from "./mapLogic";
import { CRS, registerLunarProjections } from "./projection";

registerLunarProjections();

/** South-polar 2D map: the device package's terrain shade under the catalog pins, click to identify (every CRS) and
 * leave a breadcrumb. */
export function MapView({ catalog }: { catalog: SiteCatalog }) {
  const target = useRef<HTMLDivElement>(null);
  const [picked, setPicked] = useState<Identified | null>(null);
  const [trail, setTrail] = useState<Crumb[]>([]);
  useEffect(() => {
    if (!target.current) return;
    const pins = new VectorSource({
      features: sitePins(catalog, CRS.polarSouth).map((p) => new Feature({ geometry: new Point(p.xy), name: p.label })),
    });
    const map = new OlMap({
      target: target.current,
      layers: [new VectorLayer({ source: pins })],
      view: new View({ projection: CRS.polarSouth, center: [0, 0], resolution: 500 }),
    });
    // the terrain shade, when the device package carries display tiles in this map's CRS
    fetch(`${DISPLAY_ROOT}/tiles.json`)
      .then((r) => (r.ok ? (r.json() as Promise<DisplayIndex>) : null))
      .then((index) => {
        const g = index && displayGrid(index, CRS.polarSouth);
        if (!g) return;
        const source = new XYZ({
          url: g.url,
          projection: CRS.polarSouth,
          tileGrid: new TileGrid({ extent: g.extent, origin: g.origin, resolutions: g.resolutions, tileSize: g.tileSize }),
        });
        map.getLayers().insertAt(0, new TileLayer({ source }));
      })
      .catch(() => undefined); // no package tiles: the pins still show
    map.on("singleclick", (e) => {
      const id = identify(e.coordinate as [number, number], CRS.polarSouth);
      setPicked(id);
      setTrail((t) => addBreadcrumb(t, { lat_deg: id.lat_deg, lon_deg: id.lon_deg }, 200));
    });
    return () => map.setTarget(undefined);
  }, [catalog]);
  return (
    <section aria-label="Map">
      <div ref={target} style={{ width: "100%", height: 480 }} />
      {picked && (
        <p aria-live="polite">
          {picked.lat_deg.toFixed(5)}, {picked.lon_deg.toFixed(5)} · polar {picked.polar_m.map((v) => v.toFixed(1)).join(", ")} m ·
          equirectangular {picked.equirect_m.map((v) => v.toFixed(1)).join(", ")} m · {trail.length} breadcrumbs
        </p>
      )}
    </section>
  );
}
