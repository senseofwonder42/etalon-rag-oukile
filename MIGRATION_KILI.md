# Mettre à jour le SDK Kili — ce que ça débloque pour le référentiel RAG

**En une phrase.** Le projet est épinglé à `kili==2.142.1` ; la version courante est
`26.2.0` (13 août 2026). Entre les deux, Kili a ajouté trois choses qui changent
directement notre façon de travailler : les **étapes de workflow**, un **journal
d'événements**, et les **projets LLM natifs**. Deux d'entre elles supprimeraient du
code que nous venons d'écrire faute de mieux.

**Ce document n'est pas un plan de migration.** C'est l'inventaire de ce qui devient
possible, pour décider si la mise à jour vaut son coût.

---

## 1. Où nous en sommes

Le référentiel RAG tient deux projets Kili — le référentiel de questions-réponses
validées, et la file de revue métier des réponses produites en production. Le SDK est
volontairement épinglé : la version 2.142.1 a été lue ligne à ligne, et toutes les
hypothèses sur le comportement du serveur sont documentées.

Cet épinglage a bien servi. Il a aussi un coût, qui se voit à trois endroits :

| Ce qu'on voudrait | Ce qu'on fait faute de mieux |
| --- | --- |
| Un cas de revue qui passe par deux étapes distinctes (arbitrage, puis relecture d'un brouillon) | Un horodatage posé en metadata, et une règle applicative qui retient le cas entre les deux |
| Savoir ce qui a changé depuis le dernier passage | Deux filigranes de date maison, relus à chaque exécution |
| Relancer une génération sans empiler les propositions | Rien — les propositions s'accumulent sur l'asset |

Aucun de ces trois contournements n'est grave. Tous les trois disparaissent avec la
version courante.

---

## 2. Ce que la version courante débloque

### 2.1 Les étapes de workflow — le gain le plus direct

Kili sait désormais décrire un projet comme une **suite d'étapes** (étape de travail,
étape de revue), avec des affectations par étape, un renvoi d'une étape à l'autre, et
la possibilité de filtrer les assets par étape et par statut dans l'étape.

Pour nous, c'est exactement le chaînon manquant. L'aide à la rédaction que nous venons
de mettre en place fait passer l'annotateur **deux fois** sur le même cas : il arbitre
et corrige les sources, un modèle rédige un brouillon à partir des bonnes pages, puis
il relit. Aujourd'hui ce double passage est une convention tenue par du code. Demain
c'est une propriété du projet, visible par tout le monde dans l'interface, avec des
statistiques par étape et des relecteurs désignés.

**Conséquence concrète :** la règle de rétention maison disparaît, et le pilotage de la
charge de revue devient lisible sans lire notre code.

### 2.2 Le journal d'événements — la traçabilité

Un journal interrogeable avec un curseur : « qu'est-ce qui s'est passé sur ce projet
depuis tel point ? ». Nos deux filigranes de date existent uniquement parce que le SDK
actuel ne sait pas répondre à cette question.

**Conséquence concrète :** de la traçabilité gratuite (qui a arbitré quoi, quand, dans
quel ordre) et la fin d'une classe de bugs — un filigrane mal comparé, c'est un
arbitrage métier perdu.

### 2.3 Les projets LLM natifs — l'option structurante

Kili propose désormais des types de projet dédiés aux conversations LLM. Une
conversation y est nativement une suite de messages (système, utilisateur, assistant),
et une question posée à l'annotateur peut porter **soit sur toute la conversation, soit
sur une seule réponse**. Notre file de revue est très exactement cette forme : une
question posée, une réponse générée, un arbitrage.

**Mais c'est un arbitrage lourd.** Nos cartes de revue sont composées à la main : deux
colonnes, les formulations déjà validées à gauche, la réponse à juger à droite, un
tableau des sources cliquables en dessous. Un projet LLM n'offre pas cette composition
libre : l'interface de conversation remplace la nôtre. Nous échangerions une mise en
page maîtrisée contre une interface native que nous ne contrôlons pas.

**À décider séparément.** C'est un choix produit, pas une conséquence de la mise à
jour. La mise à jour le rend possible ; elle ne l'impose pas.

### 2.4 La gouvernance des données

La création de projet accepte maintenant des **étiquettes de conformité** (`PHI`,
`PII`) pour signaler la sensibilité des données traitées, et des étiquettes
organisationnelles pour ranger les projets.

**Conséquence concrète :** nos projets manipulent des questions de sociétaires et des
extraits de conditions générales. Pouvoir marquer cette sensibilité au niveau du projet
est un argument de conformité, pas un confort de développeur.

### 2.5 Les petites choses qui font la journée

- **Remplacer une proposition au lieu de l'empiler.** Relancer une génération sur un
  cas écrase la précédente. Aujourd'hui, elles s'accumulent.
- **Déposer un label sur une étape précise** du workflow.
- **Réagir à un renvoi en file** côté automatisation (nouveau point d'accroche).
- **Copier le workflow d'un projet à l'autre** — utile le jour où on duplique le
  dispositif pour une autre ligne de produit (auto, habitation, santé).

---

## 3. Ce qu'on pourrait ajouter au produit

Au-delà du rattrapage technique, la version courante ouvre des choses que nous ne
savons pas faire aujourd'hui.

**Une file de revue à deux niveaux.** Une étape d'arbitrage tenue par les gestionnaires,
une étape de validation tenue par un référent métier, avec affectation nominative et
interdiction qu'une même personne tienne les deux rôles sur un même cas. C'est
aujourd'hui hors de portée ; ce serait une configuration.

**Un tableau de bord de charge honnête.** Combien de cas en attente, à quelle étape,
depuis combien de temps, par annotateur. Les filtres par étape et le journal
d'événements donnent la matière sans instrumentation maison.

**La génération assistée déclenchée depuis l'asset.** Le mécanisme permettant à un
annotateur de déclencher une génération sans quitter sa tâche existe — mais il est
marqué « bêta » et l'était déjà il y a quatre ans. Deux conditions à vérifier avant d'y
croire : que le code hébergé par Kili puisse appeler nos documents et notre fournisseur
de modèle, et que l'écran de l'annotateur se rafraîchisse. À prototyper, pas à
promettre.

**Dupliquer le dispositif sur une autre ligne de produit.** La copie de workflow et les
étiquettes de projet rendent la réplication raisonnable.

---

## 4. Ce que ça coûte

**Ce n'est pas une réécriture.** Tout ce dont le projet dépend aujourd'hui existe encore
dans la version courante, avec des signatures compatibles : création de projets, import
d'assets, mise à jour des cartes, lecture filtrée par metadata, labels de prédiction,
renvoi en file, vérification TLS par bundle de certificats d'entreprise. Le socle ne
bouge pas.

**Ce qu'il faut prévoir :**

| Poste | Nature |
| --- | --- |
| Revalidation sur l'instance | Notre documentation liste une vingtaine de comportements serveur constatés à l'écran. Ils sont à reconstater. C'est le poste principal. |
| Dépendances | La chaîne de dépendances a changé. Notre version de Python convient. |
| Écart de versions | 328 versions séparent les deux. Le saut mérite d'être fait dans une branche dédiée, avec la suite de tests existante comme filet — elle est fournie et tourne hors ligne. |

---

## 5. Le préalable qui décide de tout

**Quelle version notre instance Kili fait-elle tourner ?**

Le SDK peut exposer les étapes de workflow, le journal d'événements et les projets LLM
sans que notre serveur les connaisse. Nous avons déjà appris cette leçon sur le rendu
des cartes : le SDK sérialise et envoie, c'est le serveur qui décide.

Si l'instance est hébergée par Kili, la question est probablement réglée. Si elle est
installée chez nous, **c'est la première question à poser**, avant toute discussion sur
le SDK — mettre à jour la bibliothèque cliente sans mettre à jour le serveur ne
débloque rien.

Deux autres points à poser à Kili en même temps, qui conditionnent l'aide à la
rédaction déclenchée depuis l'asset :

1. Un traitement hébergé par Kili peut-il appeler des services externes (notre portail
   documentaire, notre fournisseur de modèle) ?
2. Les modèles branchés nativement dans Kili se limitent-ils toujours aux services de
   type OpenAI et Azure OpenAI ?

---

## 6. Recommandation

Une mise à jour en trois temps, du plus rentable au plus discutable.

**Temps 1 — vérifier le préalable.** Version de l'instance, et les deux questions
ci-dessus. Coût : un échange avec Kili. Sans ça, le reste est théorique.

**Temps 2 — mettre à jour et récolter l'évident.** Les étapes de workflow, le journal
d'événements, le remplacement des propositions. Ces trois-là suppriment du code
existant plutôt qu'ils n'en ajoutent, et rendent la revue lisible sans lire notre code.
C'est la partie qui se défend toute seule.

**Temps 3 — instruire les options.** Les projets LLM natifs et la génération déclenchée
depuis l'asset méritent chacun un prototype avant décision. Ni l'un ni l'autre ne doit
retarder le temps 2.

---

*Document établi à partir d'une lecture du paquet `kili 26.2.0` publié le 13 août 2026,
comparé au paquet `kili 2.142.1` installé sur le projet. Les comportements serveur n'ont
pas été éprouvés sur notre instance : c'est l'objet du temps 1.*
