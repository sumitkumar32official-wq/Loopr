"""Dev seed: python seed.py"""
from app.db import Base, SessionLocal, engine
from app.models import Society

Base.metadata.create_all(engine)
with SessionLocal() as db:
    if not db.query(Society).count():
        db.add_all([
            Society(name="Lotus Boulevard", sector="Sector 100", city="Noida", units=1120, lat=28.5446, lng=77.3910,
                    towers=["A", "B", "C", "D"]),
            Society(name="Mahagun Moderne", sector="Sector 78", city="Noida", units=3000, lat=28.5700, lng=77.3700,
                    towers=["1", "2", "3"]),
            Society(name="ATS Greens", sector="Sector 50", city="Noida", live=False),
        ])
        db.commit()
print("seeded")
