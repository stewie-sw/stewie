/* The planetary globe (§11 spine) — a THIN React boundary around a Cesium Viewer on the LUNAR ellipsoid.
 * Created once on mount; destroyed on unmount. NASA Trek (LRO WAC) imagery is added best-effort (CSP
 * already allows trek.nasa.gov in img/connect-src); the globe still shows a base colour if tiles are
 * unavailable. A left-click picks the lunar lat/lon (site selection -> drill to the local DEM work area).
 *
 * HONEST: the globe PIXELS need a real GPU browser + the tile service; headless swiftshader verifies only
 * that the Viewer mounts cleanly (no JS/CSP errors, canvas present). No Ion token is used. */
import { useEffect, useRef } from "react";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

const TREK_MOON_WAC =
  "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/default/default028mm/{z}/{reverseY}/{x}.jpg";

export function CesiumGlobe({ onPick }: { onPick?: (latDeg: number, lonDeg: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    Cesium.Ion.defaultAccessToken = ""; // no Ion assets / token
    Cesium.Ellipsoid.default = Cesium.Ellipsoid.MOON; // lunar globe, not Earth

    let viewer: Cesium.Viewer | null = null;
    try {
      viewer = new Cesium.Viewer(el, {
        baseLayer: false as unknown as Cesium.ImageryLayer, // start with no imagery -> coloured ellipsoid
        baseLayerPicker: false, geocoder: false, timeline: false, animation: false,
        homeButton: false, sceneModePicker: false, navigationHelpButton: false,
        fullscreenButton: false, infoBox: false, selectionIndicator: false,
        terrainProvider: new Cesium.EllipsoidTerrainProvider({ ellipsoid: Cesium.Ellipsoid.MOON }),
      });
      const sc = viewer.scene;
      sc.backgroundColor = Cesium.Color.fromCssColorString("#05060c");
      sc.globe.baseColor = Cesium.Color.fromCssColorString("#26262c");
      (viewer.cesiumWidget.creditContainer as HTMLElement).style.display = "none";
      viewer.scene.canvas.setAttribute("data-testid", "cesium-canvas");

      // best-effort NASA Trek lunar imagery (won't paint headless; correct source for a real GPU browser)
      try {
        viewer.imageryLayers.addImageryProvider(
          new Cesium.UrlTemplateImageryProvider({
            url: TREK_MOON_WAC,
            maximumLevel: 7,
            tilingScheme: new Cesium.GeographicTilingScheme({ ellipsoid: Cesium.Ellipsoid.MOON }),
            credit: "NASA Trek / LRO WAC",
          }),
        );
      } catch {
        /* imagery unavailable -> the coloured ellipsoid still renders */
      }

      const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      handler.setInputAction((m: { position: Cesium.Cartesian2 }) => {
        const v = viewer;
        if (!v) return;
        const cart = v.camera.pickEllipsoid(m.position, Cesium.Ellipsoid.MOON);
        if (cart && onPickRef.current) {
          const c = Cesium.Cartographic.fromCartesian(cart, Cesium.Ellipsoid.MOON);
          onPickRef.current(Cesium.Math.toDegrees(c.latitude), Cesium.Math.toDegrees(c.longitude));
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    } catch (e) {
      console.warn("Cesium init failed (needs a real GPU browser):", e);
    }

    return () => {
      if (viewer && !viewer.isDestroyed()) viewer.destroy();
    };
  }, []); // mount once

  return <div ref={ref} style={{ position: "absolute", inset: 0 }} aria-label="planetary globe" />;
}
