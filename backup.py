#!/usr/bin/env python3
"""
Backup simple de la base de datos de proyectos.
Copia data/proyectos.db → backups/proyectos_YYYY-MM-DD_HH-MM-SS.db
"""
import shutil
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "proyectos.db"
BACKUP_DIR = Path(__file__).parent / "backups"


def backup():
    if not DB_PATH.exists():
        print("❌ No se encontró la base de datos:", DB_PATH)
        return

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = BACKUP_DIR / f"proyectos_{timestamp}.db"

    shutil.copy2(DB_PATH, backup_file)
    print(f"✅ Backup creado: {backup_file}")

    # Listar backups recientes
    backups = sorted(BACKUP_DIR.glob("proyectos_*.db"), reverse=True)
    print(f"📦 Total de backups: {len(backups)}")
    for b in backups[:5]:
        size = b.stat().st_size
        print(f"   {b.name} ({size:,} bytes)")


if __name__ == "__main__":
    backup()
