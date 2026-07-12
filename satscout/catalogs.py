"""Registry of public STAC API endpoints worth searching by default.

All three are free, no-auth-required search APIs over open data. Asset
downloads from the Planetary Computer require URL signing, but metadata
search — which is all satscout does — works anonymously everywhere.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Catalog:
    id: str
    title: str
    endpoint: str  # STAC API root, no trailing slash
    notes: str = ""
    # True if the API supports the STAC `query` extension (server-side
    # filtering on properties like eo:cloud_cover). If False, satscout
    # filters client-side on the returned metadata.
    supports_query: bool = True


CATALOGS: dict[str, Catalog] = {
    c.id: c
    for c in [
        Catalog(
            id="earth-search",
            title="Earth Search (AWS Open Data)",
            endpoint="https://earth-search.aws.element84.com/v1",
            notes="Sentinel-1/2, Landsat C2, NAIP, Copernicus DEM on AWS.",
        ),
        Catalog(
            id="planetary-computer",
            title="Microsoft Planetary Computer",
            endpoint="https://planetarycomputer.microsoft.com/api/stac/v1",
            notes="120+ collections: satellite, climate (ERA5, Daymet, "
            "TerraClimate), land cover, biodiversity.",
        ),
        Catalog(
            id="usgs-landsatlook",
            title="USGS LandsatLook",
            endpoint="https://landsatlook.usgs.gov/stac-server",
            notes="Authoritative USGS Landsat Collection 2 archive.",
        ),
    ]
}


def get_catalog(catalog_id: str) -> Catalog:
    try:
        return CATALOGS[catalog_id]
    except KeyError:
        known = ", ".join(sorted(CATALOGS))
        raise KeyError(f"unknown catalog {catalog_id!r}; known catalogs: {known}") from None
