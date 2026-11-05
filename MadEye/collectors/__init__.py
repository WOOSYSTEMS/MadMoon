# MadEye Collectors Package
# All data collectors for oil, gold, and silver intelligence

from .shanghai_premium import ShanghaiPremiumCollector
from .india_premium import IndiaPremiumCollector
from .lease_rates import LeaseRatesCollector
from .options_vol import OptionsVolCollector
from .crack_variants import CrackVariantsCollector
from .comex_data import ComexDataCollector
from .refinery_regional import RefineryRegionalCollector
from .oecd_inventories import OECDInventoriesCollector
from .dark_fleet import DarkFleetCollector
from .tank_satellite import TankSatelliteCollector
from .brent_wti_spread import BrentWTISpreadCollector
from .natural_gas_sub import NaturalGasSubCollector
from .jet_fuel_demand import JetFuelDemandCollector
from .ev_impact import EVImpactCollector
from .opec_spare_capacity import OPECSpareCapacityCollector
from .us_crude_exports import USCrudeExportsCollector

# Bloomberg-gap collectors registry
BLOOMBERG_GAP_COLLECTORS = {
    "shanghai_premium": ShanghaiPremiumCollector,
    "india_premium": IndiaPremiumCollector,
    "lease_rates": LeaseRatesCollector,
    "options_vol": OptionsVolCollector,
    "crack_variants": CrackVariantsCollector,
    "comex_data": ComexDataCollector,
    "refinery_regional": RefineryRegionalCollector,
    "oecd_inventories": OECDInventoriesCollector,
    "dark_fleet": DarkFleetCollector,
    "tank_satellite": TankSatelliteCollector,
    "brent_wti_spread": BrentWTISpreadCollector,
    "natural_gas_sub": NaturalGasSubCollector,
    "jet_fuel_demand": JetFuelDemandCollector,
    "ev_impact": EVImpactCollector,
    "opec_spare_capacity": OPECSpareCapacityCollector,
    "us_crude_exports": USCrudeExportsCollector,
}

__all__ = [
    "ShanghaiPremiumCollector",
    "IndiaPremiumCollector",
    "LeaseRatesCollector",
    "OptionsVolCollector",
    "CrackVariantsCollector",
    "ComexDataCollector",
    "RefineryRegionalCollector",
    "OECDInventoriesCollector",
    "DarkFleetCollector",
    "TankSatelliteCollector",
    "BrentWTISpreadCollector",
    "NaturalGasSubCollector",
    "JetFuelDemandCollector",
    "EVImpactCollector",
    "OPECSpareCapacityCollector",
    "USCrudeExportsCollector",
    "BLOOMBERG_GAP_COLLECTORS",
]
