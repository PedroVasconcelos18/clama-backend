"""
URLs da API pública de instituições.
"""

from django.urls import path

from clama.instituicoes.api.views import InstituicaoListView

urlpatterns = [
    path("instituicoes/", InstituicaoListView.as_view(), name="instituicoes-list"),
]
