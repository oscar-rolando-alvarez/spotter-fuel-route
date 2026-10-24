"""Thin HTTP adapters: parse -> execute use case -> present. No business logic here."""

from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel_route.container import get_container
from fuel_route.domain.errors import DomainError

from .errors import error_body
from .http_cache import CACHE_CONTROL, matches, plan_etag
from .presenters import present_trip
from .serializers import PlanTripRequestSerializer

_QUERY_KEYS = ("start", "finish", "start_fuel_gallons", "stop_penalty", "strategy")


def _command(data):
    serializer = PlanTripRequestSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.to_command()


def _plan(data) -> dict:
    return present_trip(get_container().plan_trip.execute(_command(data)))


class RoutePlanView(APIView):
    """Route + cheapest fuel stops + total fuel cost.

    GET  /api/v1/route-plan/?start=Chicago, IL&finish=Denver, CO
    POST /api/v1/route-plan/  {"start": "...", "finish": "...", "start_fuel_gallons": 50}
    """

    def get(self, request):
        # Conditional GET: a matching If-None-Match is answered before any planning work.
        cmd = _command(request.query_params)
        etag = plan_etag(cmd, get_container().stations.dataset_version(), request.get_host())
        headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
        if matches(request.headers.get("If-None-Match"), etag):
            return Response(status=status.HTTP_304_NOT_MODIFIED, headers=headers)
        return self._respond(request, request.query_params, cmd, headers)

    def post(self, request):
        return self._respond(request, request.data, _command(request.data))

    def _respond(self, request, data, cmd, headers=None):
        body = present_trip(get_container().plan_trip.execute(cmd))
        query = urlencode({k: data[k] for k in _QUERY_KEYS if k in data})
        body["map_url"] = request.build_absolute_uri(f"{reverse('route-plan-map')}?{query}")
        return Response(body, headers=headers)


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
