"""Espera a que MySQL esté listo antes de iniciar servicios Docker."""

import time

from sqlalchemy import text

from dtc.db.database import engine


def main():
    last_error = None
    for attempt in range(1, 61):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print("MySQL listo.")
            return
        except Exception as exc:
            last_error = exc
            print(f"Esperando MySQL... intento {attempt}/60")
            time.sleep(2)
    raise SystemExit(f"MySQL no estuvo listo a tiempo: {last_error}")


if __name__ == "__main__":
    main()
