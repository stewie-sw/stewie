"""#274 (REG-01): mission-time solar geometry must follow the CHOSEN site, not a hardcoded Haworth
latitude. plan.py (raster overlay) + layers.py (_quantize_sun, globe drape) resolve (lat, lon) from the
site registry via sites.site_latlon and feed BOTH to sun_az_el (mirroring the already-correct
ephemeris.py) -- so shadow/illumination layers for a non-Haworth tile, AND for Haworth itself (whose
registry latitude -86.33 differs from the old hardcoded -87.45), are physically placed.
"""
from stewie.specs.sites import get_site, site_latlon


def test_site_latlon_uses_the_registry_not_the_old_hardcode():
    lat, lon = site_latlon("haworth")
    assert (lat, lon) == (get_site("haworth").lat_deg, get_site("haworth").lon_deg)
    assert abs(lat - (-86.33)) < 0.5, "Haworth must resolve to the registry latitude"
    assert abs(lat - (-87.45)) > 0.5, "must NOT be the old hardcoded -87.45 (#274)"
    # a different site resolves to ITS OWN coordinates
    assert site_latlon("faustini_rim") == (get_site("faustini_rim").lat_deg, get_site("faustini_rim").lon_deg)
    # an unknown site falls back to Haworth and never raises
    assert site_latlon("not_a_real_site") == site_latlon("haworth")


def test_quantize_sun_follows_the_chosen_site():
    """_quantize_sun must resolve a mission time at the site's geometry: Haworth and Faustini Rim (very
    different lat/lon) give a different (el, az) for the same mission time -- pre-#274 both returned the
    one hardcoded-Haworth answer."""
    from stewie.server.routers.layers import _quantize_sun
    mt = 6.0 * 3600.0                                    # a fixed mission time
    haworth = _quantize_sun(None, None, mt, "haworth")
    faustini = _quantize_sun(None, None, mt, "faustini_rim")
    assert haworth != faustini, f"resolved sun must differ by site (#274); both = {haworth}"
