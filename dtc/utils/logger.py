"""
Configuración de logging para el sistema DTC.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from dtc.config.settings import config, LOGS_DIR


def setup_logging(level: str = None):
    """Configura el sistema de logging."""
    log_level = getattr(logging, (level or config.log_level).upper(), logging.INFO)

    # Crear directorio de logs si no existe
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Formato
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    # Handler para consola
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(fmt, date_fmt))

    # Handler para archivo
    log_file = LOGS_DIR / f"dtc_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt, date_fmt))

    # Configurar root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Reducir verbosidad de librerías externas
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logging.info(f"Logging configurado. Nivel: {log_level}. Archivo: {log_file}")
