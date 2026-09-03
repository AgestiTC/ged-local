# Audit — le compteur « Relancer l'IA » est reparti de 150 à 1226 (03/09/2026)

## Ce que compte ce chiffre (code)
`GET /api/documents/maintenance/counts` → champ **`reenrich`** (le « Restant » du bouton) :

```sql
-- documents AVEC texte, NON catalogués, et SANS catégorie IA
length(coalesce(texte_extrait,'')) > 0 AND statut <> 'catalogued' AND metadonnees_ia.categorie IS NULL
```

- **Total (14620)** = docs enrichissables (`avec_texte AND statut <> 'catalogued'`).
- **Traité (13394)** = ceux qui ONT une catégorie.
- **Restant (1226)** = ceux SANS catégorie → le compteur.

Donc le chiffre monte quand des documents **arrivent (ou reviennent) sans catégorie IA**. Trois causes possibles :
1. **(le plus probable) une synchro NAS** a (ré)indexé un lot : nouveaux fichiers, ou fichiers **modifiés** re-extraits → statut `extracted`, catégorie pas encore posée.
2. **perte de métadonnées** : des lignes `metadonnees_ia` supprimées/vidées (un « Ré-analyser » ré-extrait et peut repartir de zéro).
3. le **worker d'enrichissement** est à l'arrêt → la file ne se vide plus (n'AUGMENTE pas le total, mais laisse le restant élevé si des docs sont arrivés).

## Diagnostic — à lancer sur le LXC (décisif)

```bash
cd /opt/docflow
# 1) Les 1226 sont-ils un LOT RÉCENT (synchro) ou d'anciens docs qui ont perdu leur catégorie ?
docker compose exec -T postgres psql -U docflow -d docflow -c "
SELECT d.date_import::date AS jour, count(*)
FROM documents d LEFT JOIN metadonnees_ia m ON m.document_id = d.id
WHERE length(coalesce(d.texte_extrait,'')) > 0 AND d.statut <> 'catalogued' AND m.categorie IS NULL
GROUP BY 1 ORDER BY 1 DESC LIMIT 15;"

# 2) Répartition par statut (un pic d'extracted = ré-extraction récente)
docker compose exec -T postgres psql -U docflow -d docflow -c "
SELECT statut, count(*) FROM documents GROUP BY statut ORDER BY 2 DESC;"

# 3) Synchros récentes (ont-elles tourné ce matin ?)
docker compose exec -T postgres psql -U docflow -d docflow -c "
SELECT type, statut, created_at, completed_at, resultat
FROM jobs WHERE type='sync_source' ORDER BY created_at DESC LIMIT 6;"

# 4) Le worker d'enrichissement tourne-t-il ? (jobs enrich en cours + récents)
docker compose exec -T postgres psql -U docflow -d docflow -c "
SELECT statut, count(*) FROM jobs WHERE type='enrich' GROUP BY statut;"
docker compose logs worker --tail=20 | grep -iE 'enrich|claim|budget' | tail -10
```

## Lecture des résultats
- **Requête 1** — si les 1226 sont **concentrés sur aujourd'hui/hier** → c'est un **lot fraîchement (ré)indexé** (synchro) : rien d'anormal, il suffit de laisser l'enrichissement tourner (ou cliquer « Relancer l'IA »). Si au contraire ils sont **dispersés sur d'anciennes dates** → **perte de métadonnées** (à creuser : quel événement a vidé `metadonnees_ia`).
- **Requête 3** — une `sync_source` `completed` ce matin avec un gros `resultat` (nouveaux/modifiés) **confirme** l'hypothèse 1.
- **Requête 4** — si aucun job `enrich` `running`/`pending` et rien dans les logs → le **worker n'enrichit pas** (à redémarrer : `docker compose restart worker`).

## Conclusion (à compléter avec les sorties)
> _À remplir une fois les 4 requêtes exécutées._

## Note
Le déploiement de la veille (1.63 Dossiers, migration `0002`/hiérarchie) **ne touche pas** `documents`
ni `metadonnees_ia` — il crée des tables séparées (`dossiers_thematiques`, `ressources`). Il n'est donc
**pas** la cause directe du compteur. La piste NAS/synchro est la plus vraisemblable.
