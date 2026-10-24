"""Thin HTTP adapters: parse -> execute use case -> present. No business logic here."""

from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel_route.container import get_container
from fuel_route.domain.errors import DomainError

from .errors import error_body
from .presenters import present_trip
from .serializers import PlanTripRequestSerializer

_QUERY_KEYS = ("start", "finish", "start_fuel_gallons", "stop_penalty", "strategy")


def _plan(data) -> dict:
    serializer = PlanTripRequestSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return present_trip(get_container().plan_trip.execute(serializer.to_command()))


class RoutePlanView(APIView):
    """Route + cheapest fuel stops + total fuel cost.

    GET  /api/v1/route-plan/?start=Chicago, IL&finish=Denver, CO
    POST /api/v1/route-plan/  {"start": "...", "finish": "...", "start_fuel_gallons": 50}
    """

    def get(self, request):
        return self._respond(request, request.query_params)

    def post(self, request):
        return self._respond(request, request.data)

    def _respond(self, request, data):
        body = _plan(data)
        query = urlencode({k: data[k] for k in _QUERY_KEYS if k in data})
        body["map_url"] = request.build_absolute_uri(f"{reverse('route-plan-map')}?{query}")
        return Response(body)


class RoutePlanMapView(APIView):
    """Same query as RoutePlanView, rendered on a Leaflet map (for humans / the demo)."""

    def get(self, request):
        try:
            body, code = _plan(request.query_params), 200
        except DomainError as exc:
            body, code = error_body(exc)
        return render(request, "fuel_route/map.html", {"plan": body, "ok": code == 200}, status=code)


class HealthView(APIView):
    def get(self, request):
        c = get_container()
        return Response({"status": "ok", "stations": c.stations.count(), "indexed": c.station_index.size})
