import hashlib
import json
import logging
from dataclasses import astuple
from urllib.parse import urlencode

from django.core.cache import cache
from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FuelStation
from .serializers import TripRequestSerializer
from .services.geocoding import GeocodingError
from .services.http import UpstreamError
from .services.optimizer import UnreachableError
from .services.planner import TripRequest, plan_trip
from .services.station_index import get_station_index

log = logging.getLogger(__name__)


def _cached_plan(req: TripRequest) -> dict:
    """Identical trips are served from cache (0 external calls, ~1 ms)."""
    raw = json.dumps([str(v).strip().lower() for v in astuple(req)])
    key = "plan:" + hashlib.sha1(raw.encode()).hexdigest()
    if (hit := cache.get(key)) is not None:
        return {**hit, "meta": {**hit["meta"], "cache_hit": True, "external_api_calls": 0, "elapsed_ms": 0}}
    result = plan_trip(req)
    result["meta"]["cache_hit"] = False
    cache.set(key, result)
    return result


def _run(data) -> tuple[dict, int]:
    serializer = TripRequestSerializer(data=data)
    if not serializer.is_valid():
        return {"error": "invalid_request", "detail": serializer.errors}, status.HTTP_400_BAD_REQUEST
    try:
        return _cached_plan(TripRequest(**serializer.validated_data)), status.HTTP_200_OK
    except GeocodingError as exc:
        return {"error": "location_not_found", "detail": str(exc)}, status.HTTP_400_BAD_REQUEST
    except UnreachableError as exc:
        return {"error": "no_feasible_fuel_plan", "detail": str(exc)}, status.HTTP_422_UNPROCESSABLE_ENTITY
    except UpstreamError as exc:
        log.warning("routing provider failed: %s", exc)
        return {"error": "routing_unavailable", "detail": str(exc)}, status.HTTP_502_BAD_GATEWAY


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
        body, code = _run(data)
        if code == status.HTTP_200_OK:
            query = {k: data[k] for k in ("start", "finish", "start_fuel_gallons", "stop_penalty") if k in data}
            body = {**body, "map_url": request.build_absolute_uri(f"{reverse('route-plan-map')}?{urlencode(query)}")}
        return Response(body, status=code)


class RoutePlanMapView(APIView):
    """Same query as RoutePlanView, rendered on a Leaflet map (for humans / the demo)."""

    def get(self, request):
        body, code = _run(request.query_params)
        return render(request, "fuel_route/map.html", {"plan": body, "ok": code == 200}, status=code)


class HealthView(APIView):
    def get(self, request):
        return Response({"status": "ok", "stations": FuelStation.objects.count(), "indexed": get_station_index().size})
