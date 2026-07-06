#!/usr/bin/env bash
# Per Artemis site: render DEM(colored) / hillshade / slope(colored) as pixel-aligned PNGs in the site's
# native polar-stereographic frame (no reprojection) for the 2D layered Site Inspector. Bounds come from the
# existing terrain <Site>.json x_extent/y_extent (metres, centred).
cd /mnt/projects/geolibre
mkdir -p /tmp/lyr
cat > /tmp/dem_ramp.txt <<'R'
0% 46 52 84
25% 74 84 110
50% 150 140 96
75% 200 185 140
100% 235 228 205
nv 0 0 0 0
R
cat > /tmp/slope_ramp.txt <<'R'
0 40 120 60
10 120 160 40
20 210 170 40
30 220 70 40
45 180 30 30
nv 0 0 0 0
R
for S in Site01 Site04 Site06 Site07 Site11 Site20 Site23 Site42; do
  surf=data/lunar/${S}_surf.tif
  out=apps/geolibre-desktop/public/data/layers/${S}; mkdir -p $out
  gdaldem color-relief $surf /tmp/dem_ramp.txt /tmp/lyr/${S}_dem.tif -alpha -q 2>/dev/null
  gdal_translate -q -of PNG -outsize 1500 0 /tmp/lyr/${S}_dem.tif $out/dem.png 2>/dev/null
  gdaldem hillshade $surf /tmp/lyr/${S}_hs.tif -z 2 -compute_edges -q 2>/dev/null
  gdal_translate -q -of PNG -outsize 1500 0 /tmp/lyr/${S}_hs.tif $out/hillshade.png 2>/dev/null
  gdaldem slope $surf /tmp/lyr/${S}_slp.tif -compute_edges -q 2>/dev/null
  gdaldem color-relief /tmp/lyr/${S}_slp.tif /tmp/slope_ramp.txt /tmp/lyr/${S}_slpc.tif -alpha -q 2>/dev/null
  gdal_translate -q -of PNG -outsize 1500 0 /tmp/lyr/${S}_slpc.tif $out/slope.png 2>/dev/null
  echo "  $S: $(ls $out/*.png 2>/dev/null | wc -l)/3 png"
done
rm -f $out/*.png.aux.xml apps/geolibre-desktop/public/data/layers/*/*.aux.xml 2>/dev/null
echo "ALL SITE LAYERS ENCODED"
