import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    try:
        connection = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "recruitment_db"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
        )
        print("PostgreSQL connected successfully!")
        cursor = connection.cursor()
        cursor.execute("SELECT version();")
        print(cursor.fetchone()[0])
        cursor.close()
        connection.close()
    except Exception as exc:
        print(f"Database connection failed: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
