"""
Configuración central del sistema DTC.
Todas las variables de entorno y parámetros del sistema se definen aquí.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.engine import URL

# Directorio raíz del proyecto
PROJECT_ROOT = Path(__file__).parent.parent.parent
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv(PROJECT_ROOT / ".env")

# Directorio de datos
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
LOGS_DIR = DATA_DIR / "logs"


@dataclass
class DatabaseConfig:
    """Configuración de MySQL."""
    host: str = os.getenv("DTC_DB_HOST", "localhost")
    port: int = int(os.getenv("DTC_DB_PORT", "3306"))
    database: str = os.getenv("DTC_DB_NAME", "dtc_market")
    user: str = os.getenv("DTC_DB_USER", "dtc_user")
    password: str = os.getenv("DTC_DB_PASSWORD", "dtc_password")
    driver: str = os.getenv("DTC_DB_DRIVER", "pymysql")

    @property
    def url(self) -> str:
        return URL.create(
            drivername=f"mysql+{self.driver}",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    @property
    def async_url(self) -> str:
        return URL.create(
            drivername="mysql+aiomysql",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)


@dataclass
class APIConfig:
    """Configuración de autenticación del API."""
    api_keys_raw: str = os.getenv("DTC_API_KEYS", "")

    @property
    def api_keys(self) -> set[str]:
        return {
            key.strip()
            for key in self.api_keys_raw.split(",")
            if key.strip()
        }


@dataclass
class ScraperConfig:
    """Configuración de los agentes de scraping."""
    headless: bool = True
    timeout: int = 30000  # milisegundos
    max_retries: int = 3
    crautos_max_pages: int = int(os.getenv("DTC_CRAUTOS_MAX_PAGES", "5000"))
    encuentra24_max_pages: int = int(os.getenv("DTC_ENCUENTRA24_MAX_PAGES", "5000"))
    delay_between_pages: float = 2.0  # segundos entre páginas
    delay_between_requests: float = 1.0  # segundos entre requests
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )


@dataclass
class VMUConfig:
    """Configuración del motor de Vehicle Market Units."""
    km_tolerance: int = 2000  # diferencia máxima de kilometraje (±km)
    days_to_exit: int = 5  # legado: no usar para Source Collector V2
    min_confidence_score: float = 0.7  # score mínimo para considerar match


@dataclass
class CollectorConfig:
    """Configuración del monitor liviano de presencia por fuente."""
    inactive_confirm_scans: int = int(os.getenv("DTC_INACTIVE_CONFIRM_SCANS", "3"))
    min_coverage_ratio: float = float(os.getenv("DTC_MIN_COVERAGE_RATIO", "0.85"))
    safety_min_baseline: int = int(os.getenv("DTC_SAFETY_MIN_BASELINE", "100"))
    max_detail_scrapes_per_run: int = int(
        os.getenv("DTC_MAX_DETAIL_SCRAPES_PER_RUN", "1000")
    )


@dataclass
class AppConfig:
    """Configuración principal de la aplicación."""
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    api: APIConfig = field(default_factory=APIConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    vmu: VMUConfig = field(default_factory=VMUConfig)
    log_level: str = os.getenv("DTC_LOG_LEVEL", "INFO")
    save_json_backup: bool = os.getenv("DTC_SAVE_JSON_BACKUP", "true").lower() == "true"


# Instancia global de configuración
config = AppConfig()
