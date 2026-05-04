#!/usr/bin/env python3
"""
Backup comprimido de la base de datos de proyectos.
Copia data/proyectos.db → backups/proyectos_YYYY-MM-DD_HH-MM-SS.zip
Mantiene solo los últimos 30 backups para controlar espacio en disco.
"""
import zipfile
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "proyectos.db"
BACKUP_DIR = Path(__file__).parent / "backups"
MAX_BACKUPS = 30  # Mantener últimos 30 backups


def backup():
    if not DB_PATH.exists():
        print("❌ No se encontró la base de datos:", DB_PATH)
        return

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_file = BACKUP_DIR / f"proyectos_{timestamp}.zip"

    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(DB_PATH, arcname="proyectos.db")

    print(f"✅ Backup creado: {zip_file}")

    # Rotación: eliminar backups antiguos si excedemos el límite
    backups = sorted(BACKUP_DIR.glob("proyectos_*.zip"))
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        oldest.unlink()
        print(f"🗑️  Backup antiguo eliminado: {oldest.name}")

    # Resumen
    remaining = list(BACKUP_DIR.glob("proyectos_*.zip"))
    total_size = sum(b.stat().st_size for b in remaining)
    print(f"📦 Total de backups: {len(remaining)} (ocupan {total_size:,} bytes / {total_size / (1024*1024):.1f} MB)")
    for b in sorted(remaining, reverse=True)[:5]:
        size = b.stat().st_size
        print(f"   {b.name} ({size:,} bytes)")


if __name__ == "__main__":
    backup()
