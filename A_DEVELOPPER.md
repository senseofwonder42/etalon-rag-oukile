# À développer — ce qui n'a pas pu être fait dans le POC

Ce document liste ce qui reste à faire pour la régénération des réponses non conformes
et la vérification des sources. Pour chaque point, il dit aussi **pourquoi** ce n'est pas
fait. La plupart demandent une instance Kili, une clé de modèle ou une décision métier,
qu'on n'avait pas en écrivant le code.

Ce qui est fait et comment ça marche : [REGENERATION.md](REGENERATION.md) et la section
« Régénération des réponses non conformes » du [README](README.md).

Légende : 🔴 bloquant pour un usage réel · 🟠 à faire pendant le sprint · ⚪ amélioration.

---

## 1. À constater sur l'instance — premier jour

Ces points ne demandent pas de développement, seulement un essai. Ils peuvent en
déclencher un s'ils échouent.

| | Point | Pourquoi ce n'est pas vérifié | Si ça échoue |
| --- | --- | --- | --- |
| 🔴 | **Premier appel réel au VLM** (`regenerate.py` sans `--hors-ligne`, sur 1 ou 2 cas) | Aucune clé Anthropic dans l'environnement de développement. Le chemin a été testé avec le rédacteur hors ligne et un client simulé uniquement | Erreur sur `fallbacks` : mettre `REGENERATION_FALLBACKS=false`. Erreur de modèle : changer `REGENERATION_MODEL` |
| 🔴 | **Les plugins sont ouverts sur notre offre Kili** | Fonction peut-être réservée à certaines offres | Sans plugin, la vérification par `promote.py --documents` suffit, mais le retour au métier n'arrive qu'au passage suivant, sans issue explicative |
| 🟠 | **Le plugin se construit chez Kili** : `requirements.txt` (`pydantic` v2, `loguru`), version de Python, imports `catalogue` et `rag_referentiel` depuis la racine de l'archive | Rien n'a été déployé. Testé localement en chargeant le dossier assemblé | `kili.get_plugin_build_errors(plugin_name=…)`. Si les imports échouent, mettre tout le code dans `main.py` et générer le catalogue dedans |
| 🟠 | **L'issue créée par le plugin est visible par l'annotateur**, pas seulement par les relecteurs | Comportement de l'interface | Sinon, écrire le problème dans la metadata et l'afficher sur la carte en régénérant le `json_content` |
| 🟠 | **`send_back_to_queue` sur un asset labellisé** le remet dans la file du métier | Déjà le point 4 du README | Sinon, passer par les étapes de workflow (SDK 26.x, voir [MIGRATION_KILI.md](MIGRATION_KILI.md)) |
| 🟠 | **Un label `PREDICTION` pré-remplit `VERSION_CORRIGEE`** sur l'asset de relecture | Comportement de l'interface | Rien ne casse : « Oui » sans texte promeut le brouillon stocké en metadata. Mais pour retoucher, le relecteur doit recopier le texte. Piste : un label `DEFAULT` écrit par la clé d'API, à condition de l'exclure de la relecture des arbitrages |
| 🟠 | **Délai entre la soumission et l'exécution du plugin**, et ce qui se passe si le métier resoumet entre-temps | Mesurable seulement en vrai | Voir § 3, concurrence |
| ⚪ | **Taille de la metadata d'une relecture.** Elle porte deux textes longs, le brouillon et la réponse rejetée | Le seuil réel de Kili n'est pas connu (point 2 du README) | Le repli existe déjà. Mais si la metadata est allégée, « Oui » sans texte ne retrouve plus le brouillon et le cas est rejeté (journalisé). Mesurer, puis relever ou baisser `MAX_METADATA_SIZE` |

---

## 2. Réglages à caler sur de vrais documents

| | Point | Pourquoi ce n'est pas fait |
| --- | --- | --- |
| 🟠 | **`REGENERATION_DPI`** (150 par défaut). Il faut que les tableaux les plus denses restent lisibles | Il faut de vrais PDF et de vrais appels. L'API peut aussi réduire les images trop grandes : monter la résolution n'aide pas forcément |
| 🟠 | **`REGENERATION_MAX_PAGES`** (20 par défaut). Une source sans numéro de page envoie tout le document | Les limites d'images par requête du fournisseur sont à confirmer, et le besoin réel est à mesurer |
| 🟠 | **`REGENERATION_STYLE_FILE`** : les consignes de forme du prompt de la RAG de production | Le prompt de production n'est pas dans ce dépôt. Sans lui, les brouillons suivent une forme générique qui peut s'écarter de celle de la RAG, alors qu'ils servent ensuite de référence au juge |
| ⚪ | **`REGENERATION_EFFORT`** (`high`) : comparer `medium` et `high` sur une dizaine de cas réels | Il faut une clé et des cas réels |

---

## 3. Développements identifiés

### 🟠 Vérifier que le PDF local est bien la version citée

Les sources portent une `doc_version` (par exemple `sha1:9f3c…`). Si le PDF local a
changé depuis, le brouillon est rédigé sur un autre texte que celui que le métier a vu.

**Pourquoi ce n'est pas fait :** on ne connaît pas la convention qui produit
`doc_version` (empreinte complète ou tronquée, de quoi exactement). Comparer avec une
empreinte calculée autrement signalerait des écarts sur tous les documents. À aligner
avec l'équipe qui produit les runs, puis : ajouter `DocumentStore.fingerprint()` et un
avertissement sur la carte de relecture. Ça rejoint `reverify_docs.py`.

### 🟠 Mettre à jour l'interface des projets déjà créés

Le job `CONSIGNE_CORRECTION` et la nouvelle instruction de `VERSION_CORRIGEE` ne
concernent que les projets créés à partir d'aujourd'hui. Le code fonctionne sans eux :
un projet plus ancien n'a simplement pas de consigne.

**Pourquoi ce n'est pas fait :** les projets de demain seront créés neufs. Si on doit
reprendre un projet existant, il faut un petit script qui appelle
`kili.update_properties_in_project(project_id, json_interface=REVIEW_INTERFACE)`. À
essayer d'abord sur un projet de test : changer l'interface d'un projet déjà labellisé
peut avoir des effets que le SDK ne documente pas.

### 🟠 Donner une deuxième chance au brouillon rejeté

Aujourd'hui, un brouillon refusé (« Non » sans texte réécrit) est `REJETE` et le cas
s'arrête là. C'est volontaire : ça évite une boucle sans fin.

**Pourquoi ce n'est pas fait :** il faut une décision produit. Une piste bornée : sur
une relecture « Non » avec une nouvelle consigne, rédiger **un seul** second brouillon
(compteur de générations dans la metadata), puis s'arrêter.

### 🟠 Concurrence entre le plugin et `promote.py`

Les deux réécrivent la metadata entière de l'asset. Si `promote.py` passe un cas en
`PROMU` au moment où le plugin le passe en `SOURCES_A_CORRIGER`, la dernière écriture
gagne.

**Pourquoi ce n'est pas fait :** la fenêtre est de quelques secondes, et le cycle tourne
toutes les 15 minutes au plus. Le SDK 2.142.1 n'offre aucune écriture conditionnelle.
À reconsidérer si on passe aux étapes de workflow, qui portent ce statut côté Kili.

### ⚪ Montrer les pages au relecteur

Une carte Kili TEXT n'affiche pas d'images : le relecteur ne voit pas les pages que le
VLM a lues. Il dispose des citations de pages dans le brouillon et des liens
(`DOCUMENT_URL_TEMPLATE`), dont on ne sait pas encore s'ils sont cliquables (point 13
du README).

**Pourquoi ce n'est pas fait :** il faudrait un autre type de projet (PDF ou image),
donc une autre topologie. À instruire avec la question des projets LLM natifs de
[MIGRATION_KILI.md](MIGRATION_KILI.md).

### ⚪ Suivre la relecture machinale

`drafts_edited` et `drafts_promoted` sont dans le rapport de promotion, mais rien ne
les agrège dans le temps.

**Pourquoi ce n'est pas fait :** il faut plusieurs semaines de données. Ensuite : un
taux de retouche par relecteur, et un échantillon de brouillons validés tels quels,
relus par un référent.

### ⚪ Écarter les références rédigées par le modèle du prompt du juge

Les réponses `llm_regenere` sont écrites par un modèle et servent de référence pour
juger d'autres réponses de modèle.

**Pourquoi ce n'est pas fait :** on ne sait pas encore si c'est un problème. L'origine
distincte permet de le mesurer (désaccords juge / métier selon l'origine des
références) avant de filtrer.

---

## 4. Infrastructure

| | Point | Pourquoi ce n'est pas fait |
| --- | --- | --- |
| 🟠 | **Planifier `cycle.sh`** sur le serveur Linux : crontab de l'utilisateur, ou boucle `nohup` si cron est interdit (voir « Planifier le cycle » dans le README) | Il faut un accès au serveur. `flock` est supposé présent (`util-linux`), à confirmer |
| ⚪ | **Alerter en cas d'échec** du cycle ou de relectures sans brouillon | Pas de canal défini (mail, Teams). Le rapport JSON contient déjà `failures` et `retries_pending` |
| ⚪ | **Mode temps réel** (webhook `onSubmit`) | Demande un point d'entrée joignable depuis Kili, donc une ouverture réseau. Le cycle toutes les 15 minutes couvre le besoin du POC |
| ⚪ | **Étapes de workflow Kili** (SDK 26.x) à la place de l'asset jumeau et des statuts maison | C'est une migration, voir [MIGRATION_KILI.md](MIGRATION_KILI.md) |

---

## 5. Hors périmètre, mais constaté

- **Test en échec déjà connu** : `test_an_unaccented_document_name_is_left_as_is_in_its_url`
  (nom de document accentué). Il échouait avant ces travaux et n'y est pas lié.
- **Création du projet B pour des données réelles.** Seule la démonstration le créait.
  `bootstrap_revue.py` le crée désormais, vide, comme `bootstrap.py` pour le projet A ;
  la démonstration reste un chemin séparé.
