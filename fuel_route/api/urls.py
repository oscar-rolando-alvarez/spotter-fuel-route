from django.urls import path

from . import views

urlpatterns = [
    path("route-plan/", views.RoutePlanView.as_view(), name="route-plan"),
    path("route-plan/map/", views.RoutePlanMapView.as_view(), name="route-plan-map"),
    path("health/", views.HealthView.as_view(), name="health"),
]
