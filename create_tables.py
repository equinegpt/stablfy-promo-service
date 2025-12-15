# create_tables.py
from db import engine
from models import Base

def main():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    main()
