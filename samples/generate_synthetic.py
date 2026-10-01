import csv
import random
from pathlib import Path

random.seed(42)

NOMS = ["Rakoto", "Rasoa", "Randria", "Rabe", "Andrianarivo", "Razafy",
        "Ravelo", "Rasolofo", "Rakotomalala", "Rakotoarisoa"]
PRENOMS = [("Jean", "M"), ("Marie", "F"), ("Hery", "M"), ("Naivo", "M"),
           ("Fanja", "F"), ("Tiana", "F"), ("Lalaina", "F"), ("Mamy", "M"),
           ("Soa", "F"), ("Tsiky", "F")]
FORMATIONS = [("Excel", 2024), ("Python", 2024), ("Data", 2025), ("IA", 2026)]
DOMAINS = ["gmail.com", "yahoo.fr", "hotmail.com"]


def new_phone():
    return "03" + random.choice("2348") + "".join(random.choices("0123456789", k=7))


def fmt_phone(p):
    r = random.random()
    if r < 0.4:
        return p
    if r < 0.7:
        return f"{p[:3]} {p[3:5]} {p[5:8]} {p[8:]}"
    return "+261" + p[1:]


def make_email(prenom, nom):
    return f"{prenom}.{nom}@{random.choice(DOMAINS)}".lower()


# --- Personnes de base : 40 combinaisons nom/prénom distinctes
combos = random.sample([(n, p) for n in NOMS for p in PRENOMS], 40)
people = []
for i, (nom, (prenom, sexe)) in enumerate(combos):
    people.append({"id": i, "nom": nom, "prenom": prenom, "sexe": sexe,
                   "phone": new_phone(), "email": make_email(prenom, nom)})

# --- Pièges
base = people[0]
people.append({**base, "id": 100, "phone": new_phone(),
               "email": f"{base['prenom']}{random.randint(10, 99)}@yahoo.fr".lower()})  # homonyme
fam = people[1]
people.append({"id": 101, "nom": "Rasolofo", "prenom": "Tiana", "sexe": "F",
               "phone": fam["phone"], "email": "tiana.rasolofo@gmail.com"})              # téléphone partagé


def perturb(p):
    nom, prenom, email, phone = p["nom"], p["prenom"], p["email"], fmt_phone(p["phone"])
    r = random.random()
    if r < 0.15:
        nom = nom.upper()
    elif r < 0.30:
        nom, prenom = prenom, nom                      # colonnes inversées
    elif r < 0.45:
        i = random.randrange(len(nom))
        nom = nom[:i] + nom[i] + nom[i:]               # lettre doublée
    if random.random() < 0.25:
        email = email.replace("gmail", "gmial")
    return nom, prenom, email, phone


rows = []
for p in people:
    for k in range(random.choice([1, 1, 2, 3])):
        formation, annee = random.choice(FORMATIONS)
        if k == 0:
            nom, prenom, email, phone = p["nom"], p["prenom"], p["email"], fmt_phone(p["phone"])
        else:
            nom, prenom, email, phone = perturb(p)
        rows.append({"nom": nom, "prenom": prenom, "email": email, "telephone": phone,
                     "sexe": p["sexe"], "formation": formation, "annee": annee,
                     "_truth": p["id"]})

out = Path(__file__).parent / "synthetic" / "inscriptions_demo.csv"
out.parent.mkdir(exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} inscriptions, {len(people)} personnes -> {out}")