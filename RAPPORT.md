# Rapport de livraison

Ce que ce dépôt contient, ce qui a été vérifié, et ce qui reste supposé.

## Vérifié

- `uv sync` réussit avec `kili==2.142.1` épinglé dans `pyproject.toml`.
- `uv run pytest` : **138 tests**, tous verts, **sans aucun appel réseau**
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

## Correction ciblée d'une formulation (option A)

Le job `REPONSE_VALIDEE` seul ne savait qu'**ajouter** : une petite
correction était écartée comme quasi-doublon et perdue, une réécriture
laissait la formulation fautive en place, et rien ne permettait d'en
retirer une. Trois jobs ont été ajoutés au projet A :

- `FORMULATION_CIBLE` (radio `a1`–`a5`) désigne la formulation à
  remplacer ; vide, le texte est ajouté comme avant ;
- `FORMULATIONS_A_RETIRER` (cases à cocher) retire une ou plusieurs
  formulations d'un coup ;
- chaque formulation est précédée d'un sous-titre « Réponse 1 »,
  « Réponse 2 », … — le même libellé que les catégories des deux jobs,
  de sorte que l'annotateur choisit ce qu'il lit. Le code `a1`, `a2`, …
  reste celui de la metadata, et les formulations sont **renumérotées** à
  chaque écriture pour rester dans la plage fixée par le plafond.

Les corrections multiples passent par **plusieurs enregistrements** :
`promote.py` consomme tous les labels humains créés depuis le filigrane
`derniere_promotion` de l'entrée, dans l'ordre, puis avance le filigrane.
Ce filigrane corrige au passage une perte silencieuse : la campagne ne
lisait que le **dernier** label du projet A, donc un métier annotant deux
fois voyait sa première annotation ignorée.

L'alternative « cases à cocher + jobs enfants » (une sauvegarde, N
corrections) n'a **pas** été retenue : les deux briques existent bien dans
le SDK 2.142.1, mais l'affichage des enfants sous une sélection multiple
est un comportement **serveur** non vérifiable ici. Elle reste ouverte,
et son passage ne toucherait pas au modèle de données.

## Convention de langue

Le dépôt a été retourné à la convention du cahier des charges, que la
première livraison n'avait pas respectée : **les identifiants Python sont
en anglais** — fonctions, classes, paramètres, variables et noms de tests
— et les **docstrings** le sont aussi. Reste en français tout ce qu'une
personne lit : le README, les commentaires, les messages de log et
d'erreur, les libellés et instructions des jobs Kili, et les options de
ligne de commande, reliées à un attribut anglais par le `dest`
d'argparse.

Deux exceptions assumées :

- les **noms de modules** (`referentiel.py`, `revue.py`,
  `normalisation.py`) sont conservés : l'arborescence était fixée par le
  cahier des charges, et `referentiel` / `revue` désignent les deux
  projets Kili ;
- les **noms de champs pydantic** (`statut`, `origine`, `auteur`,
  `derniere_verification`, `repli_texte`, `statut_revue`, …) sont
  conservés : ce sont les clés du `json_metadata` spécifiées dans le
  cahier des charges, relues à chaque exécution et présentes dans les
  exports JSONL. Les renommer aurait cassé le contrat de données.

Les noms des variables d'environnement de réglage suivent les champs de
`Settings` et ont donc changé (`SEUIL_APPARIEMENT_HAUT` devient
`MATCH_THRESHOLD_HIGH`, etc.) ; `KILI_API_KEY`, `KILI_API_ENDPOINT`,
`KILI_CA_BUNDLE`, `ANTHROPIC_API_KEY` et `JINA_API_KEY` sont inchangées.

## Choix et hypothèses

- **Version corrigée sur un verdict « Non ».** Le champ était présenté
  comme réservé au « Presque ». Il vaut aussi quand la réponse est
  fausse : on attend alors la bonne formulation, et elle rejoint le
  référentiel sous l'origine `metier` — elle ne doit rien à ce qu'a
  produit la RAG. La règle du cahier des charges est préservée : c'est la
  **réponse générée** qui n'entre jamais dans le référentiel sur un
  « Non », pas la correction écrite par le métier. Sans cela, le champ
  serait un piège : l'annotateur saisirait une réponse qui n'irait nulle
  part.
- **Carte de revue en deux colonnes.** La réponse à arbitrer est décalée
  à droite (`margin`, `maxWidth`)
  avec les sources qu'elle cite — elles décrivent la même prédiction — et
  les formulations validées restant à gauche. Les blocs encadrés
  partagent un gabarit commun (`BLOCK_STYLES`) : la question du
  référentiel et les formulations qui en dépendent ont la même largeur et
  le même arrondi, ce qui les aligne au lieu de laisser la question
  courir sur toute la ligne. Les titres de section ne sont pas ferrés :
  seul le contenu se déplace. Le texte
  lui-même n'est **pas** ferré à droite à l'intérieur du bloc : un
  paragraphe ou une liste ferrés à droite se lisent mal. Si le serveur
  ignore ces styles, la séparation repose encore sur les couleurs de
  fond ; c'est ajouté à la sonde et à la liste de vérification.
- **Question du référentiel sur un appariement certain.** Elle est
  désormais affichée aussi quand le cas part en `DIVERGENCE`, puisque
  les formulations montrées lui appartiennent et que la question posée
  en production est souvent une reformulation. Elle l'est **même
  lorsqu'elle est identique à la question posée** : une carte dont la
  structure varie selon les cas se lit moins bien qu'une carte qui
  répète parfois une évidence.

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
- **Remplacement ciblé et quasi-doublon.** Un remplacement désigné par
  son repère n'est pas soumis au seuil de quasi-doublon : c'est un
  arbitrage métier explicite, pas une variante à filtrer. Si le texte
  corrigé devient très proche d'une autre formulation, les deux sont
  conservées et un avertissement est journalisé — le métier peut retirer
  celle qui est en trop.
- **Retrait plutôt qu'archivage.** Une formulation retirée sort de
  `answers[]` ; il n'y a pas de statut par formulation, qui obligerait à
  filtrer partout, y compris avant l'appel au juge. La trace reste dans
  le label d'audit et dans le rapport. La dernière formulation d'une
  entrée n'est jamais retirable.
- **Format des sources.** Les pages suivent leur document
  (`doc.pdf:12 14`) plutôt que d'apparaître comme des fragments séparés.
  Une page ne se retrouve donc jamais seule, et le préfixe `p` — qui
  n'était obligatoire que dans ce cas — disparaît : l'écriture est la
  même qu'il y ait une page ou dix. L'ancienne forme (`doc.pdf:12, 14`)
  reste acceptée par tolérance, et le module `sources.py` répare les
  approximations de saisie courantes au lieu de les rejeter. Le
  formatage canonique (`format_sources`) est l'inverse exact de
  l'analyse : la liste rappelée sur la carte se recolle telle quelle
  dans le job. Le tableau de la carte groupe lui aussi par document —
  une ligne, ses pages réunies — plutôt qu'une ligne par page.
- **Intervalles de pages.** `12-14` est développé en 12, 13, 14, avec un
  plafond de 50 pages : au-delà, c'est une faute de frappe plus
  probablement qu'une intention, et l'intervalle est signalé plutôt
  qu'appliqué.
- **`KILI_CA_BUNDLE`.** Transmis à `Kili(verify=…)`, qui accepte un
  chemin comme `requests`. Un chemin invalide fait **échouer** la
  création du client : retomber sur les certificats du système sans le
  dire transformerait une erreur de configuration en faille silencieuse.
  La vérification TLS n'est jamais désactivée — aucun `verify=False`
  n'est exposé.
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
- Les repères de formulation étant renumérotés à chaque écriture, une
  promotion qui tournerait pendant qu'un métier a une carte ouverte
  pourrait décaler le repère qu'il a sous les yeux. En pratique les deux
  ne sont pas concurrentes ; c'est noté dans la liste de vérification du
  README.
- Les avertissements de dépréciation pydantic visibles pendant les tests
  proviennent de `kili` 2.142.1, qui utilise encore des validateurs de
  style pydantic v1.
