"""
Calcule les indicateurs de pilotage des stocks avec les requêtes SQL de
sql/kpi_stocks.sql (moteur DuckDB), exporte les résultats en CSV et génère le
tableau de bord autonome dashboard/index.html.

Usage : python analyse.py
"""
import json
import re
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).parent
DATA, SQL, OUT, DASH = ROOT / "data", ROOT / "sql" / "kpi_stocks.sql", ROOT / "resultats", ROOT / "dashboard"


def run_queries() -> dict[str, pd.DataFrame]:
    con = duckdb.connect()
    for table in ["articles", "fournisseurs", "mouvements_journaliers", "commandes"]:
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_csv_auto('{(DATA / (table + '.csv')).as_posix()}')")
    blocks = re.split(r"^-- name:\s*(\w+)\s*$", SQL.read_text(encoding="utf-8"), flags=re.M)[1:]
    return {name: con.execute(body).df() for name, body in zip(blocks[::2], blocks[1::2])}


def scope_payload(res: dict[str, pd.DataFrame], categorie: str | None) -> dict:
    sel = (lambda df: df) if categorie is None else (lambda df: df[df["categorie"] == categorie])
    km, art, abc, frn = sel(res["kpi_mensuels"]), sel(res["couverture_articles"]), sel(res["abc"]), sel(res["fournisseurs"])

    mois = km.groupby("mois", as_index=False).agg(
        valeur=("valeur_stock_fin_mois", "sum"), rupt=("jours_articles_en_rupture", "sum"),
        jours=("jours_articles", "sum"), dem=("qte_demandee", "sum"), serv=("qte_servie", "sum"))
    mensuel = [{"mois": r.mois, "valeur_stock": round(r.valeur, 0),
                "taux_rupture": round(r.rupt / r.jours, 4), "taux_service": round(r.serv / r.dem, 4)}
               for r in mois.itertuples()]

    total_val = abc["valeur_consommee"].sum()
    classes = [{"classe": c, "nb_articles": int((abc["classe_abc"] == c).sum()),
                "part_valeur": round(abc.loc[abc["classe_abc"] == c, "valeur_consommee"].sum() / total_val, 4)}
               for c in "ABC"]

    f = frn.assign(p=frn["delai_prevu_moyen_j"] * frn["nb_commandes"], r=frn["delai_reel_moyen_j"] * frn["nb_commandes"],
                   t=frn["taux_retard"] * frn["nb_commandes"]) \
        .groupby(["fournisseur_id", "raison_sociale"], as_index=False)[["nb_commandes", "p", "r", "t"]].sum()
    fournisseurs = [{"id": r.fournisseur_id, "nom": r.raison_sociale, "nb_commandes": int(r.nb_commandes),
                     "delai_prevu": round(r.p / r.nb_commandes, 1), "delai_reel": round(r.r / r.nb_commandes, 1),
                     "taux_retard": round(r.t / r.nb_commandes, 4)} for r in f.itertuples()]

    return {
        "kpis": {
            "valeur_stock": round(float(art["valeur_stock_eur"].sum()), 0),
            "taux_service": round(float(km["qte_servie"].sum() / km["qte_demandee"].sum()), 4),
            "taux_rupture": round(float(km["jours_articles_en_rupture"].sum() / km["jours_articles"].sum()), 4),
            "couverture_mediane": round(float(art["couverture_jours"].median()), 1),
            "nb_articles": int(len(art)),
            "nb_sous_point_commande": int((art["statut"] == "Sous le point de commande").sum()),
            "nb_surstock": int((art["statut"] == "Surstock (> 60 j)").sum()),
            "valeur_excedent_30j": round(float(art["valeur_excedent_30j_eur"].sum()), 0),
        },
        "mensuel": mensuel,
        "abc": classes,
        "fournisseurs": fournisseurs,
    }


def main():
    res = run_queries()
    OUT.mkdir(exist_ok=True)
    for name, df in res.items():
        df.to_csv(OUT / f"{name}.csv", index=False)

    abc_map = res["abc"].set_index("code_article")["classe_abc"]
    articles = res["couverture_articles"].assign(classe_abc=lambda d: d["code_article"].map(abc_map))
    payload = {
        "periode": "Année 2025",
        "categories": sorted(res["couverture_articles"]["categorie"].unique().tolist()),
        "scopes": {"Toutes": scope_payload(res, None)}
                  | {c: scope_payload(res, c) for c in res["couverture_articles"]["categorie"].unique()},
        "articles": json.loads(articles.to_json(orient="records", force_ascii=False)),
    }
    template = (DASH / "template.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    (DASH / "index.html").write_text(html, encoding="utf-8")

    k = payload["scopes"]["Toutes"]["kpis"]
    print(f"Valeur du stock au 31/12 : {k['valeur_stock']:,.0f} €")
    print(f"Taux de service : {k['taux_service']:.1%} | jours-articles en rupture : {k['taux_rupture']:.1%}")
    print(f"Articles sous le point de commande : {k['nb_sous_point_commande']} | en surstock : {k['nb_surstock']}")
    print(f"Trésorerie immobilisée au-delà de la couverture cible de 30 jours : {k['valeur_excedent_30j']:,.0f} €")


if __name__ == "__main__":
    main()
