# Rapport de livraison

Ce que ce dépôt contient, ce qui a été vérifié, et ce qui reste supposé.

## Vérifié

- `uv sync` réussit avec `kili==2.142.1` épinglé dans `pyproject.toml`.
- `uv run pytest` : **89 tests**, tous verts, **sans aucun appel réseau**
  (faux client Kili en mémoire, `FakeEmbeddings`, `JugeLexical`,
  `httpx.MockTransport` pour la sonde de disponibilité du modèle Jina).
- `uv run ruff check .` ne signale rien (`line-length = 79`, docstrings
  Google, signatures publiques typées).
- `uv run python scripts/generate_sample_data.py` produit les deux JSONL
  (12 entrées de référentiel, 15 occurrences de production).
- Les huit scripts se chargent et exposent leur `--help`.
- Le chemin complet démo → arbitrage → promotion a été exécuté **contre le
  faux client Kili** : 12 entrées importées, 10 cas de revue créés
  (6 `MATCH` dont 4 conformes, 2 `INCERTAIN`, 6 `NOUVELLE`, 1 occurrence
  ignorée pour question vide), puis promotion (6 nouvelles entrées,
  8 variantes, 2 désaccords juge / métier) et **relance sans effet**
  (idempotence).
- Les faits sur le SDK ont été **relus dans la roue installée** :
  absence de `kili.llm`, de `LLM_STATIC` et de toute clé `level` ;
  `InputType` réel ; exclusivité `content` / `json_content` pour un asset
  TEXT (`services/asset_import/text.py`) ; `json_metadatas` accepte un
  dict, `json_contents` exige une **chaîne** (`@typechecked`) ;
  `append_labels(label_type="INFERENCE")` n'exige pas de `model_name`,
  contrairement à `PREDICTION`.

## Non vérifiable sans instance Kili

Repris en tête du README, section « À vérifier au premier run » :

1. le rendu rich text côté **serveur** — c'est la seule chose que
   `probe_richtext.py` permet de trancher en cinq minutes ;
2. la taille maximale réelle d'un `json_metadata` (seuil prudent de
   60 000 octets, avec repli documenté et testé) ;
3. l'acceptation par le serveur d'un `json_content` envoyé **en ligne**
   par `update_properties_in_assets` — à l'import il transite par un
   bucket, à la mise à jour non ;
4. le comportement de `send_back_to_queue` sur un asset **déjà labellisé** ;
5. la disponibilité de `jina-embeddings-v5-nano` et l'existence du point
   d'entrée `GET /v1/models` chez Jina ;
6. l'acceptation des deux `json_interface` (catégories sans clé `id`) ;
7. la visibilité dans l'interface des labels de type `INFERENCE` servant
   de piste d'audit ;
8. le chemin d'URL d'un projet, reconstruit depuis l'endpoint GraphQL.

## Choix et hypothèses

- **Normalisation BM25.** Les scores BM25 ne sont pas bornés ; ils sont
  ramenés dans `[0, 1]` en divisant par le score qu'obtient chaque entrée
  face à elle-même. Les seuils par défaut (0.72 / 0.45) ont été calés sur
  le jeu factice avec le matcher lexical ; ils sont à re-régler sur des
  données réelles, avec le vrai backend d'embeddings.
- **Similarité partagée.** La « mécanique de similarité » réutilisée pour
  écarter les quasi-doublons et choisir les variantes les plus diverses
  est un indice de Jaccard sur les jetons normalisés — BM25 n'étant pas
  symétrique, il ne convient pas à cet usage.
- **Repli de metadata.** L'allègement retire les textes longs mais
  **conserve la question** : sans elle, l'entrée ne serait plus
  indexable. Conséquence assumée : `promote.py` refuse d'enrichir une
  entrée repliée plutôt que de dédoublonner à l'aveugle.
- **Auteur des variantes.** `answers[].auteur` porte le métier qui a
  arbitré dans le projet B, recopié depuis le label. La clé d'API reste
  l'auteur technique du label écrit dans A : le SDK ne permet pas
  d'usurper l'auteur d'un label sans l'identifiant interne de
  l'utilisateur.
- **Piste d'audit en `INFERENCE`.** Un label `DEFAULT` écrit par
  `promote.py` serait relu au run suivant comme un arbitrage humain et
  rejoué indéfiniment dès qu'une variante sort par le plafond de
  diversité. Le type `INFERENCE` coupe cette boucle.
- **`th` rendu en `td` gras.** Kili n'accepte pas l'élément `th` ;
  l'en-tête de tableau est rendu par un `td` en gras sur fond gris.
- **Désaccord juge / métier.** Il n'est connu qu'après arbitrage : il est
  donc compté dans le rapport de `promote.py`, pas dans celui de
  `monitor_run.py`.
- **Un script en plus.** `export_referentiel.py` a été ajouté pour livrer
  l'export JSONL demandé dans les sorties ; il n'apparaissait pas dans
  l'arborescence indicative.
- **Un module en plus.** `richtext.py` (briques du format) et `labels.py`
  (lecture des labels et metadata) évitent de dupliquer ces primitives
  entre `rendering.py`, `markdown_to_richtext.py`, `referentiel.py` et
  `revue.py`.

## Limites connues

- `FakeEmbeddings` est un sac de mots haché : il reproduit le
  recouvrement lexical, pas la sémantique. Les reformulations franches
  (« accident de voiture » pour « sinistre auto ») ne remontent donc pas
  en `MATCH` dans la démonstration hors ligne — c'est précisément ce que
  le backend Jina doit apporter.
- La démonstration ne simule pas d'arbitrage métier : elle s'arrête à la
  création des cas de revue, ce qui est l'objet de la démonstration —
  montrer l'interface.
- Les avertissements de dépréciation pydantic visibles pendant les tests
  proviennent de `kili` 2.142.1, qui utilise encore des validateurs de
  style pydantic v1.
