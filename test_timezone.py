#!/usr/bin/env python3
"""Test rápido: verifica que la zona horaria de Chile funciona."""
from datetime import datetime
from zoneinfo import ZoneInfo

TZ_CHILE = ZoneInfo("America/Santiago")

def now_chile():
    return datetime.now(TZ_CHILE).strftime("%Y-%m-%d %H:%M:%S")

print("Hora según Python (Chile):", now_chile())
print("Hora según sistema (UTC): ", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
print("Hora local del sistema:   ", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
