"""Domain errors. The API layer maps each one to an HTTP status in one place (api/errors.py)."""


class DomainError(Exception):
    """Base class for expected, user-facing failures."""

    code = "domain_error"


class LocationNotFoundError(DomainError):
    code = "location_not_found"


class NoFeasiblePlanError(DomainError):
    """A stretch of the route has no station within the vehicle's reach."""

    code = "no_feasible_fuel_plan"

    def __init__(self, at_mile: float, gap_miles: float):
        self.at_mile = at_mile
        self.gap_miles = gap_miles
        super().__init__(f"No fuel station reachable after mile {at_mile:.0f} (gap of {gap_miles:.0f} mi)")


class ProviderUnavailableError(DomainError):
    """An external routing/geocoding provider failed after retries."""

    code = "routing_unavailable"


class UnknownStrategyError(DomainError):
    code = "unknown_strategy"
