"""One-time migration to bring an existing MySQL `parkoptima` database in
line with the current SQLAlchemy models.

This is idempotent: it only adds tables/columns that are missing, so it is
safe to run multiple times. Existing data is preserved.

Run with:  python backend/migrate.py
(or set DATABASE_URL to point at your MySQL instance first)
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text


def main() -> None:
    DATABASE_URL = os.getenv(
        "DATABASE_URL", "mysql+pymysql://root:@localhost/parkoptima"
    )
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        # ── audit_logs table ──
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(120),
                    user_email VARCHAR(255),
                    user_role VARCHAR(60),
                    action_type VARCHAR(80) NOT NULL,
                    reference_id VARCHAR(120),
                    details TEXT,
                    timestamp DATETIME(6) DEFAULT CURRENT_TIMESTAMP(6)
                )
                """
            )
        )

        # ── users: add missing columns ──
        existing = {
            r[0]
            for r in conn.execute(text("SHOW COLUMNS FROM users")).fetchall()
        }
        user_cols = {
            "status": "VARCHAR(20) NOT NULL DEFAULT 'Active'",
            "plate_number": "VARCHAR(32)",
            "contact": "VARCHAR(30)",
            "vehicle_type": "VARCHAR(40)",
            "brand": "VARCHAR(60)",
            "model": "VARCHAR(60)",
            "color": "VARCHAR(40)",
        }
        for col, definition in user_cols.items():
            if col not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {definition}"))
                print(f"users: added column {col}")

        # ── system_settings: add missing capacity columns ──
        existing_ss = {
            r[0]
            for r in conn.execute(text("SHOW COLUMNS FROM system_settings")).fetchall()
        }
        ss_cols = {
            "total_motor_slots": "INT NOT NULL DEFAULT 50",
            "total_four_wheel_slots": "INT NOT NULL DEFAULT 50",
        }
        for col, definition in ss_cols.items():
            if col not in existing_ss:
                conn.execute(
                    text(f"ALTER TABLE system_settings ADD COLUMN {col} {definition}")
                )
                print(f"system_settings: added column {col}")

    print("Migration complete.")


if __name__ == "__main__":
    main()
