"""
URLs da API de planos.
"""

from django.urls import path

from clama.plans.api.views import PlanListView

urlpatterns = [
    path("planos/", PlanListView.as_view(), name="plan-list"),
]
