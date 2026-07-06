cd /mnt/projects/geolibre
for S in Site01 Site04 Site06 Site07 Site11 Site20 Site23 Site42; do
  python3 scripts/encode_terrain_points.py data/lunar/${S}_surf.tif \
    apps/geolibre-desktop/public/data/terrain/${S}.bin \
    apps/geolibre-desktop/public/data/terrain/${S}.json 2>&1 | tail -1
done
echo "ALL 8 ENCODED"
