from rest_framework import serializers


class TripRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text="'City, ST', 'lat,lng' or an address")
    finish = serializers.CharField(max_length=200)
    start_fuel_gallons = serializers.FloatField(
        required=False, min_value=0, max_value=50, help_text="Fuel in the tank at departure; default full (50)"
    )
    stop_penalty = serializers.FloatField(
        required=False, min_value=0, max_value=500, help_text="USD cost per stop; 0 = cheapest fuel regardless of stops"
    )
