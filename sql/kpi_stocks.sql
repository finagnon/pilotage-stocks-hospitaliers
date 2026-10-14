-- =====================================================================
-- Pilotage des stocks hospitaliers : indicateurs clés (SQL DuckDB)
-- Tables : articles, fournisseurs, mouvements_journaliers, commandes
-- Chaque bloc commence par "-- name: <nom>" et est exécuté par analyse.py
-- =====================================================================

-- name: kpi_mensuels
-- Valeur du stock en fin de mois, demande, quantité servie et jours en rupture,
-- par mois et par catégorie.
WITH m AS (
    SELECT
        date_trunc('month', CAST(mv.date AS DATE))           AS mois,
        a.categorie,
        mv.code_article,
        CAST(mv.date AS DATE)                                 AS jour,
        mv.quantite_demandee,
        mv.quantite_servie,
        mv.stock_fin_journee * a.prix_unitaire_eur            AS valeur_stock,
        CASE WHEN mv.quantite_servie < mv.quantite_demandee THEN 1 ELSE 0 END AS jour_rupture
    FROM mouvements_journaliers mv
    JOIN articles a USING (code_article)
),
fin_de_mois AS (
    SELECT mois, categorie, SUM(valeur_stock) AS valeur_stock_fin_mois
    FROM m
    WHERE jour = last_day(mois)
    GROUP BY mois, categorie
)
SELECT
    strftime(m.mois, '%Y-%m')                 AS mois,
    m.categorie,
    f.valeur_stock_fin_mois,
    SUM(m.quantite_demandee)                  AS qte_demandee,
    SUM(m.quantite_servie)                    AS qte_servie,
    SUM(m.jour_rupture)                       AS jours_articles_en_rupture,
    COUNT(*)                                  AS jours_articles
FROM m
JOIN fin_de_mois f USING (mois, categorie)
GROUP BY m.mois, m.categorie, f.valeur_stock_fin_mois
ORDER BY m.mois, m.categorie;

-- name: couverture_articles
-- Situation de chaque article au 31/12 : couverture en jours (stock / consommation
-- moyenne des 90 derniers jours), statut et valeur immobilisée au-delà de la
-- couverture cible de 30 jours.
WITH conso90 AS (
    SELECT code_article, AVG(quantite_servie) AS conso_moy_jour
    FROM mouvements_journaliers
    WHERE CAST(date AS DATE) > DATE '2025-12-31' - INTERVAL 90 DAY
    GROUP BY code_article
),
dernier AS (
    SELECT code_article, stock_fin_journee AS stock_final
    FROM mouvements_journaliers
    WHERE CAST(date AS DATE) = DATE '2025-12-31'
),
ruptures AS (
    SELECT code_article,
           SUM(CASE WHEN quantite_servie < quantite_demandee THEN 1 ELSE 0 END) AS jours_rupture_annee,
           SUM(quantite_servie) * 1.0 / NULLIF(SUM(quantite_demandee), 0)        AS taux_service
    FROM mouvements_journaliers
    GROUP BY code_article
)
SELECT
    a.code_article, a.libelle, a.categorie, a.fournisseur_id,
    d.stock_final, a.point_commande,
    ROUND(c.conso_moy_jour, 2)                                        AS conso_moy_jour,
    ROUND(d.stock_final / NULLIF(c.conso_moy_jour, 0), 1)            AS couverture_jours,
    ROUND(d.stock_final * a.prix_unitaire_eur, 2)                     AS valeur_stock_eur,
    ROUND(GREATEST(d.stock_final - 30 * c.conso_moy_jour, 0) * a.prix_unitaire_eur, 2)
                                                                      AS valeur_excedent_30j_eur,
    r.jours_rupture_annee,
    ROUND(r.taux_service, 4)                                          AS taux_service,
    CASE
        WHEN d.stock_final <= a.point_commande                        THEN 'Sous le point de commande'
        WHEN d.stock_final / NULLIF(c.conso_moy_jour, 0) > 60         THEN 'Surstock (> 60 j)'
        ELSE 'Normal'
    END                                                               AS statut
FROM articles a
JOIN dernier d  USING (code_article)
JOIN conso90 c  USING (code_article)
JOIN ruptures r USING (code_article)
ORDER BY a.code_article;

-- name: abc
-- Classification ABC (Pareto) sur la valeur consommée de l'année :
-- A = 80 % de la valeur, B = 80-95 %, C = le reste.
WITH v AS (
    SELECT a.code_article, a.libelle, a.categorie,
           SUM(mv.quantite_servie) * a.prix_unitaire_eur AS valeur_consommee
    FROM mouvements_journaliers mv
    JOIN articles a USING (code_article)
    GROUP BY a.code_article, a.libelle, a.categorie, a.prix_unitaire_eur
),
cumul AS (
    SELECT *,
           SUM(valeur_consommee) OVER (ORDER BY valeur_consommee DESC
                                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             / SUM(valeur_consommee) OVER () AS part_cumulee
    FROM v
)
SELECT code_article, libelle, categorie, ROUND(valeur_consommee, 2) AS valeur_consommee,
       ROUND(part_cumulee, 4) AS part_cumulee,
       CASE WHEN part_cumulee <= 0.80 THEN 'A'
            WHEN part_cumulee <= 0.95 THEN 'B'
            ELSE 'C' END AS classe_abc
FROM cumul
ORDER BY valeur_consommee DESC;

-- name: fournisseurs
-- Fiabilité des délais fournisseurs sur les commandes réceptionnées.
SELECT
    f.fournisseur_id,
    f.raison_sociale,
    a.categorie,
    COUNT(*)                                                    AS nb_commandes,
    ROUND(AVG(c.delai_prevu_j), 1)                              AS delai_prevu_moyen_j,
    ROUND(AVG(c.delai_reel_j), 1)                               AS delai_reel_moyen_j,
    ROUND(AVG(CASE WHEN c.delai_reel_j > c.delai_prevu_j THEN 1 ELSE 0 END), 4) AS taux_retard
FROM commandes c
JOIN fournisseurs f USING (fournisseur_id)
JOIN articles a     USING (code_article)
WHERE c.delai_reel_j IS NOT NULL
GROUP BY f.fournisseur_id, f.raison_sociale, a.categorie
ORDER BY f.fournisseur_id, a.categorie;
