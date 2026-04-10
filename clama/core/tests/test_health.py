"""
Testes para o endpoint de healthcheck.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from clama.core import __version__


@pytest.mark.django_db
class TestHealthCheckView:
    """Testes para o endpoint GET /api/health/."""

    def setup_method(self):
        self.client = APIClient()

    def test_health_returns_200(self):
        """Healthcheck deve retornar status 200."""
        response = self.client.get("/api/health/")
        assert response.status_code == 200

    def test_health_returns_status_ok(self):
        """Healthcheck deve retornar status='ok'."""
        response = self.client.get("/api/health/")
        assert response.data["status"] == "ok"

    def test_health_returns_version(self):
        """Healthcheck deve retornar a versão atual."""
        response = self.client.get("/api/health/")
        assert response.data["version"] == __version__

    def test_health_returns_timestamp(self):
        """Healthcheck deve retornar timestamp ISO 8601."""
        response = self.client.get("/api/health/")
        assert "timestamp" in response.data
        # Verifica formato ISO 8601 (ex: 2024-01-15T10:30:00Z)
        timestamp = response.data["timestamp"]
        assert "T" in timestamp

    def test_health_returns_database_status(self):
        """Healthcheck deve retornar status do banco de dados."""
        response = self.client.get("/api/health/")
        assert "database" in response.data
        assert response.data["database"] in ["ok", "error"]

    def test_health_has_all_required_keys(self):
        """Healthcheck deve retornar todas as 4 chaves esperadas."""
        response = self.client.get("/api/health/")
        assert set(response.data.keys()) == {"status", "version", "timestamp", "database"}

    def test_health_no_auth_required(self):
        """Healthcheck deve funcionar sem autenticação."""
        # Não passamos credenciais
        response = self.client.get("/api/health/")
        assert response.status_code == 200
