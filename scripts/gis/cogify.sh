cd /mnt/projects/geolibre
mkdir -p apps/geolibre-desktop/public/data/cog
for S in Site01 Site04 Site06 Site07 Site11 Site20 Site23 Site42; do
  o=apps/geolibre-desktop/public/data/cog/$S; mkdir -p $o
  gdal_translate -q -of COG -co COMPRESS=DEFLATE -co PREDICTOR=3 -co BLOCKSIZE=512 data/lunar/${S}_surf.tif $o/dem.tif 2>/dev/null
  gdaldem slope data/lunar/${S}_surf.tif /tmp/${S}_slp.tif -compute_edges -q 2>/dev/null
  gdal_translate -q -of COG -co COMPRESS=DEFLATE -co BLOCKSIZE=512 /tmp/${S}_slp.tif $o/slope.tif 2>/dev/null
  echo "  $S cog: $(ls $o/*.tif 2>/dev/null|wc -l)"
done
# 1m Haworth
gdal_translate -q -of COG -co COMPRESS=DEFLATE -co PREDICTOR=3 -co BLOCKSIZE=512 data/lunar/Haworth_1m_sfs.tif apps/geolibre-desktop/public/data/cog/Haworth_1m_dem.tif 2>/dev/null
echo "ALL COGS DONE ($(du -sh apps/geolibre-desktop/public/data/cog 2>/dev/null|cut -f1))"
