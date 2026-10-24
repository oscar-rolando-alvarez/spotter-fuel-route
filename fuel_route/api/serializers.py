from rest_framework import serializers

from fuel_route.application.plan_trip import PlanTripCommand
from fuel_route.domain.optimizer import STRATEGIES


class PlanTripRequestSerializer(serializers.Serializer):
    """Input DTO: validates the request and produces the use-case command."""

    start = serializers.CharField(max_length=200, help_text="'City, ST', 'lat,lng' or an address")
    finish = serializers.CharField(max_length=200)
    start_fuel_gallons = serializers.FloatField(
        required=False, min_value=0, max_value=50, help_text="Fuel in the tank at departure; default full (50)"
    )
    stop_penalty = serializers.FloatField(
        required=False, min_value=0, max_value=500, help_text="USD cost per stop; 0 = cheapest fuel regardless of stops"
    )
    strategy = serializers.ChoiceField(choices=sorted(STRATEGIES), default="dp")

    def to_command(self) -> PlanTripCommand:
        return PlanTripCommand(**self.validated_data)
