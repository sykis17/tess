"""Quick Phase 15B routing smoke tests — run `pytest tests/test_pov_routing.py` for full matrix."""
from tests.test_pov_routing import (
    test_ionic_bonding_replaces_wrong_biology_pov,
    test_pov_registry_has_five_agents,
    test_science_app_ui_routes_art_and_ui_design,
)

test_ionic_bonding_replaces_wrong_biology_pov()
test_science_app_ui_routes_art_and_ui_design()
test_pov_registry_has_five_agents()

print("All Phase 15B smoke tests passed")
