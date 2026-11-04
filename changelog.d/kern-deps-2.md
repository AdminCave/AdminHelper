### Changed

- **Server, Monitoring, CA-Issuer: Python-Pakete auf dem aktuellen Stand:** FastAPI 0.162 (in allen drei Diensten
  gleich), Starlette 1.10, SQLAlchemy 2.1, Alembic 1.20, Pydantic 2.14, Uvicorn 0.54, websockets 17, redis-py 8.1,
  cryptography 50.0.2 und psycopg 3.3.7; die Locks sind neu erzeugt. Der CA-Issuer braucht greenlet nicht mehr.
