# -*- coding: utf-8 -*-
"""
Tests basicos para la Plataforma de Proyectos.
Uso: pytest tests/
"""
import pytest
from datetime import date
from utils import now_chile, hoy_chile, hora_chile, dias_habiles, ascii_safe


class TestUtils:
    """Tests de funciones puras en utils.py."""

    def test_now_chile_formato(self):
        result = now_chile()
        # Debe ser YYYY-MM-DD HH:MM:SS
        assert len(result) == 19
        assert result[4] == "-"
        assert result[7] == "-"
        assert result[10] == " "
        assert result[13] == ":"
        assert result[16] == ":"

    def test_hoy_chile_formato(self):
        result = hoy_chile()
        assert len(result) == 10
        assert result[4] == "-"
        assert result[7] == "-"

    def test_hora_chile_formato(self):
        result = hora_chile()
        assert len(result) == 5
        assert result[2] == ":"

    def test_dias_habiles_positivo(self):
        # Lunes a viernes = 5 dias habiles
        result = dias_habiles(date(2024, 1, 1), date(2024, 1, 5))
        assert result == 5

    def test_dias_habiles_invertido(self):
        # Fecha fin < fecha inicio
        result = dias_habiles(date(2024, 1, 10), date(2024, 1, 1))
        assert result == -1

    def test_dias_habiles_mismo_dia(self):
        result = dias_habiles(date(2024, 1, 8), date(2024, 1, 8))  # lunes
        assert result == 1

    def test_ascii_safe_acentos(self):
        assert ascii_safe("áéíóú") == "aeiou"
        assert ascii_safe("ÁÉÍÓÚ") == "AEIOU"

    def test_ascii_safe_tildes(self):
        assert ascii_safe("niño") == "nino"
        assert ascii_safe("años") == "anos"

    def test_ascii_safe_comillas(self):
        assert ascii_safe('"hola"') == '"hola"'
        assert ascii_safe("'hola'") == "'hola'"

    def test_ascii_safe_none(self):
        assert ascii_safe(None) == ""


class TestAppBasic:
    """Tests de integracion minimos para la app Flask."""

    def test_app_importa(self):
        # Solo verifica que app.py pueda importarse sin errores
        import app
        assert app.app is not None
        assert app.app.secret_key is not None

    def test_ruta_index_status(self):
        import app
        client = app.app.test_client()
        # Sin base de datos la ruta puede fallar, pero no con 500 inesperado
        response = client.get("/", follow_redirects=True)
        # Debe retornar 200 o redirect valido, nunca 500
        assert response.status_code in (200, 302, 404)
