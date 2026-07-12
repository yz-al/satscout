"""satscout — find, vet, and validate public satellite/climate datasets.

Two jobs, straight from user research with remote-sensing scientists:

1. Discovery: search the big public STAC catalogs (AWS Earth Search,
   Microsoft Planetary Computer, USGS LandsatLook) by area of interest,
   time range, and keywords — and inspect scene metadata (cloud cover,
   bands, resolution) WITHOUT downloading any imagery.

2. Validation: good-practice accuracy assessment and area estimation for
   remote-sensing products per Olofsson et al. (2014), "Good practices
   for estimating area and assessing accuracy of land change",
   Remote Sensing of Environment 148:42-57.
"""

__version__ = "0.1.0"

from .catalogs import CATALOGS, Catalog
from .olofsson import AccuracyAssessment, assess, design_sample

__all__ = ["CATALOGS", "Catalog", "AccuracyAssessment", "assess", "design_sample"]
