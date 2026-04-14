from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Lokal:
# Benutzer: pflege
# Passwort: pflegepass
# DB-Name: pflege
# Host: localhost, Port: 5432 (Standard)
DATABASE_URL = "postgresql+psycopg2://pflege:pflegepass@localhost:5432/pflege"

engine = create_engine(
    DATABASE_URL,
    echo=False,  # bei Bedarf True zum Debuggen
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()