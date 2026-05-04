# -*- coding: utf-8 -*-
"""
Utilidades compartidas de la Plataforma de Proyectos.
Extraidas de app.py para reducir acoplamiento y facilitar tests.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ_CHILE = ZoneInfo("America/Santiago")


def now_chile(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Devuelve fecha/hora actual en Chile como string."""
    return datetime.now(TZ_CHILE).strftime(fmt)


def hoy_chile() -> str:
    """Devuelve solo la fecha actual en Chile (YYYY-MM-DD)."""
    return now_chile("%Y-%m-%d")


def hora_chile() -> str:
    """Devuelve solo la hora actual en Chile (HH:MM)."""
    return now_chile("%H:%M")


def fecha_hora_compacta() -> str:
    """Devuelve fecha y hora corta (YYYY-MM-DD HH:MM)."""
    return now_chile("%Y-%m-%d %H:%M")


def dias_habiles(fecha_inicio, fecha_fin):
    """Cuenta días hábiles entre dos fechas (inclusive), excluyendo sábados y domingos."""
    if fecha_fin < fecha_inicio:
        return -1
    dias = 0
    current = fecha_inicio
    while current <= fecha_fin:
        if current.weekday() < 5:
            dias += 1
        current += timedelta(days=1)
    return dias


def ascii_safe(text):
    """Convierte texto a ASCII basico para compatibilidad con fuentes core de FPDF2."""
    if text is None:
        return ""
    t = str(text)
    t = t.replace("\u2014", "-").replace("\u2013", "-")
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    trans = str.maketrans(
        "áéíóúÁÉÍÓÚñÑüÜ¿¡",
        "aeiouAEIOUnNuU?!"
    )
    return t.translate(trans)
