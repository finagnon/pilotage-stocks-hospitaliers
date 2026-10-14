"""
Génère un jeu de données 100 % FICTIF de pharmacie hospitalière (année 2025).

- Aucune donnée patient, aucune donnée personnelle : uniquement des articles,
  des fournisseurs fictifs, des consommations agrégées par jour et des commandes.
- Simulation d'une politique de réapprovisionnement (point de commande / quantité
  fixe) avec des délais fournisseurs aléatoires, pour faire apparaître des ruptures
  et des surstocks réalistes.

Usage : python generate_data.py   (graine fixe -> résultats reproductibles)
"""
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 2025
DATA = Path(__file__).parent / "data"
START, END = "2025-01-01", "2025-12-31"

rng = np.random.default_rng(SEED)

FOURNISSEURS = [
    # id, raison sociale fictive, délai prévu (j), fiabilité (écart-type du retard)
    ("FRN-01", "Laboratoire Alpha (fictif)", 5, 1.0),
    ("FRN-02", "Pharma Bêta (fictif)", 7, 5.0),
    ("FRN-03", "Medica Gamma (fictif)", 4, 1.5),
    ("FRN-04", "Dispomed Delta (fictif)", 10, 8.0),
    ("FRN-05", "Solutés Epsilon (fictif)", 3, 0.8),
    ("FRN-06", "Nutri Zêta (fictif)", 6, 2.5),
]

# catégorie, (prix min, prix max), (conso jour min, max), fournisseurs possibles, unité
CATEGORIES = {
    "Anticancéreux injectables": ((120, 1800), (0.5, 4), ["FRN-01", "FRN-02"], "flacon"),
    "Antibiotiques": ((4, 60), (5, 40), ["FRN-02", "FRN-03"], "flacon"),
    "Antalgiques": ((0.5, 8), (20, 120), ["FRN-03", "FRN-01"], "ampoule"),
    "Solutés de perfusion": ((1, 6), (40, 200), ["FRN-05"], "poche"),
    "Dispositifs médicaux stériles": ((2, 90), (10, 80), ["FRN-04"], "unité"),
    "Nutrition clinique": ((6, 35), (5, 30), ["FRN-06"], "poche"),
}

LIBELLES = {
    "Anticancéreux injectables": ["Cisplatine 50 mg", "Carboplatine 450 mg", "Paclitaxel 300 mg",
                                  "Oxaliplatine 100 mg", "Docétaxel 160 mg", "Gemcitabine 1 g",
                                  "Irinotécan 300 mg", "Pembrolizumab 100 mg"],
    "Antibiotiques": ["Amoxicilline 1 g", "Ceftriaxone 1 g", "Pipéracilline-tazobactam 4 g",
                      "Vancomycine 500 mg", "Méropénem 1 g", "Gentamicine 80 mg",
                      "Céfazoline 2 g", "Métronidazole 500 mg"],
    "Antalgiques": ["Paracétamol 1 g inj.", "Néfopam 20 mg", "Kétoprofène 100 mg",
                    "Tramadol 100 mg", "Morphine 10 mg", "Kétamine 50 mg",
                    "Lidocaïne 1 %", "Ondansétron 8 mg"],
    "Solutés de perfusion": ["NaCl 0,9 % 100 mL", "NaCl 0,9 % 500 mL", "Glucose 5 % 500 mL",
                             "Ringer lactate 500 mL", "Glucose 10 % 250 mL", "KCl 10 % 10 mL",
                             "Bicarbonate 1,4 % 500 mL", "Eau ppi 10 mL"],
    "Dispositifs médicaux stériles": ["Cathéter périphérique 20G", "Seringue 50 mL",
                                      "Prolongateur 3 voies", "Aiguille Huber 20G",
                                      "Compresse stérile 10x10", "Perfuseur par gravité",
                                      "Gants stériles T7", "Pansement transparent"],
    "Nutrition clinique": ["Nutrition parentérale 1 L", "Nutrition parentérale 2 L",
                           "Complément oral HP/HC", "Nutrition entérale 500 mL",
                           "Émulsion lipidique 250 mL", "Oligo-éléments 10 mL",
                           "Vitamines inj.", "Complément oral sans lactose"],
}


def build_products() -> pd.DataFrame:
    rows, n = [], 1
    for cat, (prix, conso, frns, unite) in CATEGORIES.items():
        for lib in LIBELLES[cat]:
            frn = rng.choice(frns)
            delai = dict((f[0], f[2]) for f in FOURNISSEURS)[frn]
            conso_moy = float(np.round(rng.uniform(*conso), 2))
            prix_u = float(np.round(np.exp(rng.uniform(np.log(prix[0]), np.log(prix[1]))), 2))
            # paramétrage du réapprovisionnement : volontairement imparfait
            profil = rng.choice(["ok", "sous-dimensionne", "sur-dimensionne"], p=[0.6, 0.2, 0.2])
            secu_j = {"ok": 4, "sous-dimensionne": 0, "sur-dimensionne": 20}[profil]
            stock_secu = int(np.ceil(conso_moy * secu_j))
            couv_delai = 0.6 if profil == "sous-dimensionne" else 1.0
            point_cde = int(np.ceil(conso_moy * delai * couv_delai + stock_secu))
            qte_cde = int(np.ceil(conso_moy * {"ok": 21, "sous-dimensionne": 14, "sur-dimensionne": 75}[profil]))
            rows.append({
                "code_article": f"ART-{n:04d}", "libelle": lib, "categorie": cat, "unite": unite,
                "prix_unitaire_eur": prix_u, "fournisseur_id": frn, "conso_moy_jour_ref": conso_moy,
                "stock_securite": stock_secu, "point_commande": point_cde, "qte_commande": qte_cde,
            })
            n += 1
    return pd.DataFrame(rows)


def simulate(products: pd.DataFrame):
    dates = pd.date_range(START, END, freq="D")
    frn = {f[0]: f for f in FOURNISSEURS}
    daily, orders = [], []
    num_cde = 1
    for p in products.itertuples():
        stock = int(p.point_commande + p.qte_commande * rng.uniform(0.3, 1.5))
        pending = []  # (date_reception, qte, num)
        for d in dates:
            # réceptions du jour
            for rec in [x for x in pending if x[0] <= d]:
                stock += rec[1]
                pending.remove(rec)
            # demande : saisonnalité (hiver +15 %), creux le week-end, bruit de Poisson
            saison = 1 + 0.15 * np.cos((d.dayofyear - 15) / 365 * 2 * np.pi)
            we = 0.55 if d.dayofweek >= 5 else 1.0
            demande = int(rng.poisson(p.conso_moy_jour_ref * saison * we))
            servie = min(stock, demande)
            stock -= servie
            daily.append((d.date().isoformat(), p.code_article, demande, servie, stock))
            # déclenchement de commande (stock + en-cours <= point de commande)
            en_cours = sum(x[1] for x in pending)
            if stock + en_cours <= p.point_commande and d.dayofweek < 5:
                _, _, delai_prevu, sigma = frn[p.fournisseur_id]
                delai_reel = max(1, int(round(delai_prevu + abs(rng.normal(0, sigma)) - 0.5)))
                rec_date = d + pd.Timedelta(days=delai_reel)
                pending.append((rec_date, int(p.qte_commande), num_cde))
                orders.append({
                    "num_commande": f"CDE-{num_cde:05d}", "code_article": p.code_article,
                    "fournisseur_id": p.fournisseur_id, "date_commande": d.date().isoformat(),
                    "date_reception": rec_date.date().isoformat() if rec_date <= dates[-1] else None,
                    "quantite": int(p.qte_commande), "delai_prevu_j": delai_prevu,
                    "delai_reel_j": delai_reel if rec_date <= dates[-1] else None,
                })
                num_cde += 1
    daily_df = pd.DataFrame(daily, columns=["date", "code_article", "quantite_demandee",
                                            "quantite_servie", "stock_fin_journee"])
    return daily_df, pd.DataFrame(orders)


def main():
    DATA.mkdir(exist_ok=True)
    products = build_products()
    daily, orders = simulate(products)
    fournisseurs = pd.DataFrame(
        [{"fournisseur_id": f[0], "raison_sociale": f[1], "delai_prevu_j": f[2]} for f in FOURNISSEURS])
    products.drop(columns=["conso_moy_jour_ref"]).to_csv(DATA / "articles.csv", index=False)
    fournisseurs.to_csv(DATA / "fournisseurs.csv", index=False)
    daily.to_csv(DATA / "mouvements_journaliers.csv", index=False)
    orders["delai_reel_j"] = orders["delai_reel_j"].astype("Int64")
    orders.to_csv(DATA / "commandes.csv", index=False)
    print(f"{len(products)} articles, {len(daily):,} lignes journalières, {len(orders):,} commandes")


if __name__ == "__main__":
    main()
