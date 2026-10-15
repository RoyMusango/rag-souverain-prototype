# Journal de bord — donnees experimentales

Projet : Recherche hybride securisee pour un RAG souverain
Auteur : Roy Ebwelle — UMONS / CETIC — stage 01/07/2026 au 01/10/2026
Derniere mise a jour : 01/09/2026

---

## 1. Environnement d execution

| Element | Valeur |
|---|---|
| Date d execution | 03-04/08/2026 |
| Systeme | Windows, PowerShell |
| Python | 3.11 |
| JDK (Synthea) | Temurin 25.0.4.7 (JAVA_HOME force, PATH portant un JRE 1.8) |
| Chemin racine | C:\Dev\rag-souverain |
| Depot Git | https://github.com/RoyMusango/rag-souverain (prive) |
| Cache HuggingFace | C:\Dev\hf_cache (hors depot) |
| Modeles NER | spaCy en_core_web_lg, fr_core_news_lg |

Note : aucun accelerateur graphique. Toute extraction NER s execute sur CPU,
ce qui explique les durees rapportees en section 6.

---

## 2. Volumetries brutes recuperees

| Corpus | Volume brut | Taille disque | Remarques |
|---|---|---|---|
| Synthea | 1165 patients, 18 CSV | ~810 Mo | graine 42, Massachusetts |
| EnronQA | 221 316 lignes, 4 parquet | 0,62 Go | 150 boites confirmees |
| FinQA | 8281 paires (train 6251, dev 883, test 1147) | 26,8 Mo | test conserve, non utilise |
| TAT-QA | 2479 contextes, 14 883 questions | 4,84 Mo | split test non public |
| PubMedQA | 273 518 (labeled 1000, unlabeled 61 249, artificial 211 269) | ~300 Mo | evaluation sur pqa_labeled |
| Sanctions UE | 6239 entrees | 24 Mo | instantane du 31/07/2026, XML 1.0 |
| EUR-Lex | 4 textes, 8 PDF (FR + EN) | ~11 Mo | RGPD, DORA, AI Act, MiFID II |

---

## 3. Parametres de generation Synthea

| Parametre | Valeur |
|---|---|
| Commande | .\run_synthea.bat -p 10000 -s 42 Massachusetts |
| Population demandee | 10000 |
| Graine (-s) | 42 |
| Etat | Massachusetts |
| Patients obtenus | 11538 |
| Ecart explique | Synthea genere aussi les patients decedes au cours de la periode simulee ; 1000 vivants + 165 decedes |
| Export | CSV active, FHIR desactive |

---

## 4. Resultats d ingestion (schema commun)

| Corpus | Documents | Rubriques | Entites | Entites/doc | Texte moyen | Vides | Filtres |
|---|---|---|---|---|---|---|---|
| Synthea | 45 883 | 11 538 | 1 547 784 | 33,7 | 3046 car. | 0 | 269 |
| FinQA | 7134 | 2409 | 342 503 | 48,0 | 4028 car. | 0 | 0 |
| TAT-QA | 14 354 | 2479 | 93 656 | 6,5 | 310 car. | 0 | 0 |
| PubMedQA (partiel) | 62 249 | 2 | 962 971 | 15,5 | 1371 car. | 0 | 0 |
| PubMedQA (integral) | 273 518 | 3 | 3 738 641 | 13,7 | 1394 car. | 0 | 0 |
| EUR-Lex (v1 defaillante) | 918 | 25 | 31 902 | 34,8 | 4255 car. | 0 | 0 |
| EUR-Lex (v2 corrigee) | 4393 | 202 | 36 931 | 8,4 | 875 car. | 0 | 3 doublons ecartes |
| EnronQA | 73 772 | 150 | 2 159 916 | 29,3 | 2270 car. | 0 | 0 |

---

## 5. Decisions de conception a l ingestion

### 5.1 Correspondance rubrique / page / pave

| Corpus | rubrique | page | pave |
|---|---|---|---|
| Synthea | dossier patient (identifiant) | 1 | rang de la section (identite, conditions, observations, medications) |
| EnronQA | boite aux lettres (champ user) | 1 | rang du courriel dans la boite |
| FinQA | rapport source (champ filename) | 1 | rang du contexte dans le rapport |
| TAT-QA | identifiant de table (uid) | 1 | rang du paragraphe ; le tableau porte le pave 1 |
| PubMedQA | configuration | 1 | rang de l abstract |
| EUR-Lex | article du reglement | page du PDF | rang du paragraphe dans l article |

**Limite assumee.** Cinq corpus sur six ont page = 1 : ni un courriel ni un
abstract n ont de pagination native. Seul EUR-Lex exerce les quatre niveaux de
la chaine document -> rubrique -> page -> pave. C est la raison pour laquelle
EUR-Lex sert de corpus de demonstration pour l invariant I3, et pourquoi la
qualite de sa segmentation conditionne l experience E4.

### 5.2 Synthea — bornage des rubriques

MAX_LIGNES_PAR_RUBRIQUE = 40.

Motif : la rubrique observations peut compter plusieurs centaines de lignes par
patient (une par mesure clinique). Sans bornage, elle produirait des documents
demesures qui domineraient l index et fausseraient la comparaison entre
rubriques. La valeur 40 conserve un contenu clinique representatif tout en
maintenant une longueur de document comparable aux autres corpus (1675
caracteres en moyenne, contre 2270 pour EnronQA).

269 rubriques ont ete filtrees car vides : ce sont des patients sans prescription medicamenteuse (medications : 11 269 sur 11 538, soit 2,3 %).

### 5.3 Synthea — suffixes numeriques des noms

Synthea suffixe les noms d un nombre pour garantir l unicite (Wallace647
Effertz744). Ces suffixes sont retires du texte a l ingestion.

Motif : conserver ces chaines fausserait toute mesure de rappel du masquage NER,
aucun modele n ayant vu de tels tokens a l entrainement. Le rappel mesure serait
artificiellement bas et non transposable a un corpus reel. L unicite reste
assuree par l identifiant patient, qui n apparait pas dans le texte.

### 5.4 EnronQA — deduplication

221 316 lignes brutes ont produit 73 772 courriels uniques, soit 147 544 lignes
redondantes ecartees (facteur 3,0).

Motif : chaque courriel apparait une fois par question posee a son sujet. Sans
deduplication par le champ path, chaque courriel serait indexe trois fois en
moyenne et tout denominateur de rappel serait errone.

Les 528 304 paires question-reponse sont conservees separement dans
data/enronqa/enronqa_qa.jsonl, hors du schema documentaire.

**Ecart a documenter.** L article annonce 103 638 courriels ; la deduplication
par path en produit 73 772. L ecart (28,8 %) peut provenir du filtrage des
courriels reduits a une signature (seuil de 40 caracteres de corps utile), ou
d une definition differente de l unite documentaire par les auteurs. A verifier
avant redaction du chapitre 4 ; a mentionner dans tous les cas.

### 5.5 PubMedQA — etiquetage externe

PubMedQA est etiquete source = "externe" alors que son contenu est fiable.

Motif : il joue le role de substitut controle du web biomedical ouvert. Il sera
donc traite comme contenu non fiable par la couche d isolation (I2). Un corpus
reproductible vaut mieux qu un web changeant pour une evaluation replicable.

### 5.6 FinQA et TAT-QA — splits de test exclus

FinQA : le split test (1147 paires) est telecharge mais non ingere, afin de
conserver une evaluation finale non contaminee.

TAT-QA : les reponses du split test ne sont pas publiques (soumission au
leaderboard). L evaluation porte sur dev uniquement. Rapporter des chiffres
"test" serait une erreur detectable.


### 5.7 Revision de la taille de population Synthea

Premiere generation : 1000 patients demandes, 1165 obtenus.
Diagnostic : 83,9 % des patients etaient deja uniques sur la combinaison des
sept quasi-identifiants, avant toute requete. La courbe d effondrement de |S|
aurait demarre quasiment a plat, faute d ensemble d anonymat initial a reduire.

Cause : 273 villes et 254 codes postaux pour 1165 patients, soit des ensembles
de 4 a 5 patients en moyenne. La population etait trop petite au regard du
nombre de modalites geographiques.

Correction retenue : regeneration a 10 000 patients, graine 42 inchangee.
11 538 patients obtenus. Le nombre de villes du Massachusetts croissant
faiblement (415 contre 273, soit x1,5 pour une population x9,9), la taille
moyenne des ensembles d anonymat augmente nettement : le taux de patients
uniques passe de 83,9 % a 46,2 %, ce qui restitue une marge de mesure a E2.

Alternative ecartee : retirer ville et code postal des quasi-identifiants pour
ne conserver que le comte (14 modalites). Ecartee car la generalisation
geographique est precisement le mecanisme de protection etudie en section 3.3.3
du rapport : la traiter comme un pretraitement reviendrait a mesurer la
protection sur des donnees deja protegees.




### 5.9 EUR-Lex — etat de la segmentation par articles

Adaptateur v1 : 918 documents, 25 rubriques, un document par page.
Cause : decoupage par double saut de ligne, que pypdf.extract_text() ne
produit pas. Le motif d en-tete d article n etait teste qu en debut de page.

Adaptateur v2 (decoupage ligne a ligne) : 4681 documents, 755 rubriques,
142 pages distinctes, pave maximal de 129 dans une rubrique. La chaine
document -> rubrique -> page -> pave est donc effectivement instanciee, ce
qu aucun autre corpus ne permet.

Segmentation par texte (releve du 01/09/2026) :

| Texte | Articles detectes | Attendus |
|---|---|---|
| AI Act EN | 113 | 113 |
| AI Act FR | 113 | 113 |
| DORA EN | 64 | 64 |
| DORA FR | 64 | 64 |
| MiFID II EN | 98 | 97 |
| MiFID II FR | 97 | 97 |
| RGPD EN | 99 | 99 |
| RGPD FR | 99 | 99 |

Lecture : les quatre textes sont desormais segmentes par article dans les
deux langues, a l unite pres sur MiFID II EN. Un releve anterieur, consigne
ici jusqu au 31/08/2026, rapportait 0 article detecte pour le RGPD, DORA et
l AI Act, et 4393 documents pour 202 rubriques ; il correspondait a une
version anterieure de l adaptateur et ne decrit plus le schema produit.

Consequence pour E4 : la limitation qui restreignait la mesure
d attribuabilite a quatre niveaux au seul MiFID II est levee. L experience
porte sur les quatre textes.

### 5.10 Synthea — strategie de selection des observations

Le bornage initial (40 premieres lignes) a ete abandonne apres analyse de la
distribution reelle.

Diagnostic : la rubrique observations compte 358 lignes par patient en
mediane, 758 en moyenne, jusqu a 26 539 au maximum. Un plafond de 40 lignes
ne conservait le dossier complet que pour 0,2 % des patients, et meme un
plafond de 200 lignes n en couvrait que 20,4 %. La troncature devenait la
regle et non l exception.

Defaut plus grave que le volume : chaque patient presente 63 types
d observation distincts en mediane (99 au p90). Garder les 40 premieres
lignes chronologiques conservait des mesures repetees d une meme
consultation — taille, poids, tension — et perdait au moins 23 types
cliniques, dont les resultats de laboratoire discriminants. La granularite
du plafond n etait pas en cause : c est la troncature en tete qui est
inadaptee a un dossier medical.

Strategie retenue : conserver la DERNIERE valeur de chaque type
d observation. Justification clinique — un dossier se lit par ce qui est a
jour, non par l historique exhaustif.

Resultat : 63 lignes conservees en mediane (p90 : 99 ; max : 148), soit
100 % des types cliniques et aucune troncature pour la moitie des patients.
Taille de la rubrique : 5206 caracteres en mediane, comparable a FinQA
(4028) et dans un facteur 2,3 d EnronQA (2270), ce qui preserve
l equilibre de la normalisation par longueur de BM25.

Aucun plafond arbitraire ne subsiste : la deduplication par type borne la
rubrique d elle-meme.


### 5.11 Corpus interne bancaire synthetique

Genere par src/ingestion/banque.py, graine 42, 300 dossiers clients.

| Element | Valeur |
|---|---|
| Notes | 1500 (5 par dossier) |
| Rubriques | 300 (un dossier client) |
| Texte moyen | 258 caracteres |
| Entites de verite terrain | 6900 |
| dont PERSONNE | 2400 |
| dont IDENTIFIANT | 2100 |
| dont IBAN | 900 |
| dont LIEU / ORGANISATION | 600 / 600 |
| dont CARTE | 300 |

Motif : Synthea ne contient aucun identifiant bancaire. Les reconnaisseurs
deterministes de confidentialite/verrou.py n etaient donc eprouves par
aucune experience, et le rappel mesure par E7 etait lu a tort comme la
performance de la chaine complete.

Les IBAN satisfont le reste modulo 97 et les cartes la cle de Luhn. Un corpus
d identifiants invalides mesurerait la detection de forme et non la detection
d identifiants, et interdirait toute evaluation ulterieure d une validation
par somme de controle. Le generateur s auto-controle au lancement.

Verite terrain : chaque note est composee a partir d un enregistrement
structure, on connait donc exactement quelles chaines sont sensibles et de
quelle categorie. Meme discipline que pour E2 et E7 sur Synthea.

Limite assumee : les notes sont courtes (258 caracteres contre 2270 pour
EnronQA) et engendrees a partir de cinq gabarits. Ce corpus convient a la
mesure du masquage, qui procede par entite ; il ne convient pas a la mesure
de la recuperation, ou la normalisation par longueur de BM25 ne s y
comporterait pas comme sur les corpus reels.

---

## 6. Durees observees (CPU seul, sans GPU)

| Etape | Duree |
|---|---|
| Build Synthea (gradlew) | ~15 min (premier build) |
| Generation 1000 patients | ~5 min |
| Telechargement EnronQA (666 Mo) | variable |
| Ingestion Synthea (4636 docs) | quelques minutes |
| Ingestion FinQA (7134 docs) | 24 min |
| Ingestion TAT-QA (14 354 docs) | 6 min |
| Ingestion PubMedQA partielle (62 249 docs) | ~1 h |
| Ingestion PubMedQA integrale (273 518 docs) | ~5 h |
| Ingestion EnronQA (73 772 docs) | 39 min |

Ces durees justifient la strategie de mesure du chapitre 4 : le precalcul des
embeddings et leur persistance sont indispensables, une re-execution complete
etant incompatible avec l iteration.

---

## 7. Conformite et licences

| Element | Valeur |
|---|---|
| NOTICE.md cree | oui, convention TASL |
| Captures de licence archivees | A COMPLETER (7 attendues, docs/licences/) |
| Demande de regularisation EnronQA | A COMPLETER (date, URL) |
| Reponse des auteurs | A COMPLETER |
| Saisine du DPO CETIC | A COMPLETER (date, destinataire) |

---

## 8. Difficultes rencontrees

| Etape | Probleme | Resolution | Temps perdu |
|---|---|---|---|
| Prerequis | Java 1.8 present, Synthea exige 11+ | Installation Temurin 25, JAVA_HOME force manuellement (l installeur ne renseigne pas la variable par defaut) | ~30 min |
| Git | data\external\eurlex cree comme FICHIER et non dossier par Move-Item | Suppression, mkdir explicite, retelechargement d un PDF | ~15 min |
| TAT-QA | UnicodeDecodeError a la lecture JSON | open(..., encoding="utf-8") — l encodage par defaut de Windows est cp1252 | ~5 min |
| Sanctions UE | URL EEAS de la procedure obsolete (404) | Bascule vers le portail data.europa.eu | ~10 min |
| EUR-Lex | Segmentation par articles defaillante (0 a 9 articles detectes sur 64 a 113 attendus) | Adaptateur v2 : decoupage ligne a ligne au lieu de \\n\\n, pypdf ne produisant pas de double saut de ligne. Resultat partiel : MiFID II segmente correctement (98 articles sur 97), RGPD, DORA et AI Act restent non segmentes (0 article) | ~2 h |
| PubMedQA / EnronQA | Extraction NER de plusieurs heures sur CPU | nlp.pipe avec composant ner seul ; option --sans-artificial pour iterer | — |

Cette section n est pas anecdotique : les difficultes de traitement des donnees
constituent un contenu legitime du chapitre 4, et un jury les prefere a un
recit lisse.

---

## 9. Premiers ordres de grandeur (index)

A COMPLETER apres construction de l index Qdrant.

| Mesure | Valeur | Materiel |
|---|---|---|
| Debit d embedding BGE-M3 | 0,5 doc/s (769 docs EUR-Lex en 25,9 min) | ultraportable, 4 fils, float32 |
| Debit indicatif attendu sur accelerateur | A COMPLETER | instance GPU |
| Taille de l index Qdrant | A COMPLETER | |
| Construction de l index lexical BM25 | 22 a 30 s pour 73 772 courriels | ultraportable |
| Latence de recuperation BM25 | 639 ms mediane, 955 ms p90 | ultraportable, rank_bm25 sans index inverse |
| Latence dense / fusion | A COMPLETER | |

Note : la latence BM25 releve d une implementation en Python pur qui calcule
un score contre chacun des 73 772 documents a chaque appel. Elle n est pas
representative d un deploiement a index inverse.

---

## 10. Population d entites pour E2

| Element | Valeur |
|---|---|
| Entites (patients) | 11538 |
| Quasi-identifiants retenus | ville, cp, comte, genre, race, ethnie, tranche_age |
| Palier d age | 10 ans |
| Date de reference | 2026-08-03 (figee pour reproductibilite) |
| Exclus | Id, SSN, DRIVERS, PASSPORT, LAT, LON, INCOME, HEALTHCARE_* |
| Motif d exclusion | identifiants directs ou continus : |S| = 1 immediat, mesure triviale plutot que representative |
| Patients uniques sur combinaison complete | 5333 sur 11538 (46,2 %) |

Lecture : ce dernier pourcentage est la proportion de patients deja
re-identifiables sans aucune protection. C est le point de depart de la courbe
d effondrement de |S|.

---

## 11. Resultats des experiences

Relevés du 31/08/2026 au 07/09/2026. Chaque sous-section nomme le fichier
de résultat dont elle est tirée, sous `resultats/`.

Deux avertissements valent pour toute la section. Toute valeur antérieure au
correctif d'appariement d'E7 (31/08) est sous-évaluée et ne doit pas être
citée. Et toute valeur de E7 ou E7b antérieure au correctif de normalisation
des étiquettes du 01/09 est fausse sur la catégorie ORGANISATION, pour la
raison exposée plus bas.

### 11.0 Conventions de mesure

Trois conventions valent pour toutes les campagnes de detection ci-dessous.
Elles ont ete arretees le 01/09/2026, avant les executions rapportees, et
s'appliquent uniformement a E7 et a E7b. Ne pas les melanger.

**Le denominateur du rappel est le nombre d'OCCURRENCES.** `positions_attendues`
localise chaque chaine sensible dans chaque texte : une ville citee deux fois
compte deux fois. Le compte de chaines DISTINCTES — 2121 sur Synthea, 2400 sur
le corpus bancaire — est une autre grandeur, publiee separement sous le nom
`chaines_distinctes`. Les valeurs de 2121 et 2400 qui figuraient auparavant a
cote d'un rappel etaient des denominateurs faux : les bons sont 2712 et 6900.

**La precision se calcule sur les DETECTIONS**, soit
`(detections - faux_positifs) / detections`. La formule precedente,
`VP / (VP + FP)`, additionnait un numerateur compte au niveau des entites de
reference et un denominateur melant references et detections. Depuis le
correctif d'appariement du 31/08, une detection peut apparier plusieurs entites
de reference, si bien que `VP` pouvait depasser le nombre de detections : sur
E7, 2427 vrais positifs pour 2058 detections. La formule avantageait donc les
detecteurs produisant des empans longs, c'est-a-dire precisement la chaine
souveraine que ce travail defend. Le JSON expose les deux, `precision` et
`precision_par_reference`, afin que la bascule reste tracable ; seule la
premiere est citee dans le rapport.

Effet chiffre du changement de convention, a modele et a detections inchanges :

| Execution | precision (detections) | precision_par_reference |
|---|---|---|
| E7 spaCy | 0,835 | 0,877 |
| E7 Presidio | 0,833 | 0,867 |
| E7b spaCy | 0,897 | 0,913 |
| E7b Presidio | 0,892 | 0,903 |

**L'appariement exige la categorie dans la ventilation par categorie, et non
au niveau global.** Voir la convention detaillee en 11.0.1 ci-dessous.

### E1a — recuperation lexicale seule, EnronQA

200 questions echantillonnees (graine 42) sur 73 772 courriels.

| k | 1 | 3 | 5 | 10 | 20 | 50 |
|---|---|---|---|---|---|---|
| Rappel@k | 0,660 | 0,840 | 0,880 | 0,910 | 0,930 | 0,965 |
| nDCG@k | 0,660 | 0,767 | 0,783 | 0,792 | 0,798 | 0,805 |

MRR 0,757. Sept questions sur 200 ne sont satisfaites par aucun des 50
premiers resultats.

Validation externe : Ryan et al. rapportent 0,875 de rappel@5 avec BM25 sur
ce corpus ; nous mesurons 0,880. L ecart n est pas significatif sur 200
tirages, mais l absence d ecart systematique valide la chaine d ingestion, et
notamment l unite documentaire retenue (73 772 courriels apres deduplication
par chemin, contre 103 638 annonces par la publication).

### E2 — effondrement de l ensemble d anonymat, Synthea

20 entites, population 11 538, k = 50, budget 6 bits, trace « progression ».

| Configuration | S_T | sous k | emises | deficit (bits) | violations |
|---|---|---|---|---|---|
| Gabarit et budget par session | 100,5 | 20 % | 9,60 | 6,565 | 80 % |
| Gabarit par session, budget par entite | 100,5 | 20 % | 3,55 | 0,714 | 15 % |
| Gabarit et budget par entite | 121,5 | 0 % | 5,50 | 0,000 | 0 % |

Source : `resultats/e2_controle/resume.json`, cibles tirees au hasard.

Les colonnes S_T et « sous k » relevent du mode a effort constant, les
autres du mode reel.

#### Ce que la population protege d'elle-meme : rien

Mesure directe sur `data/synthea/entities.json`, sans passer par E2.

| Apres divulgation des 7 quasi-identifiants | Synthea | Banque |
|---|---|---|
| Population | 11 538 | 300 |
| Quasi-identifiants | 7 | 4 |
| \|S\| median par personne | **2** | **1** |
| \|S\| moyen | 2,1 | 1,5 |
| Plus grande classe d'equivalence | 13 | 4 |
| Part des personnes seules | 46,2 % | 59,3 % |
| Part des personnes a \|S\| >= 50 | **0 %** | **0 %** |

**La plus grande classe n'est pas l'ensemble d'anonymat initial.** Celui-ci
vaut N, 11 538, puisque rien n'est encore divulgue : c'est le premier point de
la courbe. Les 13 sont le PLANCHER, le meilleur cas apres divulgation
complete. La confusion est facile et vaut d'etre ecrite ici.

La consequence est la premisse d'E2 : la population n'apporte aucune
protection, donc tout ce que mesure la campagne vient de la regle de comptage.
Les 121,5 de C3 ne sont pas une population genereuse, c'est un arret a
mi-chemin d'un effondrement a 2.

**Pourquoi E2 ne tourne pas sur le corpus bancaire.** Avec un seul attribut
divulgue, la part des clients encore a \|S\| >= 50 vaut :

| Attribut divulgue | ville | region | secteur | tranche_encours |
|---|---|---|---|---|
| Part a \|S\| >= 50 | **0 %** | 54,0 % | 57,7 % | **0 %** |

Deux des quatre attributs font tomber tout le monde sous le seuil des leur
divulgation. Il resterait deux attributs utilisables et une seule question
avant l'effondrement : la campagne mesurerait la taille du corpus, pas la
regle. Synthea offre en plus une echelle de generalisation — ville vers comte,
plus tranche d'age, genre, origine — dont les quatre attributs bancaires ne
disposent pas.

**Une formulation trop forte a circule le 21/09** : « k = 50 impossible a
satisfaire des la premiere question » sur le corpus bancaire. Elle est fausse,
region et secteur laissent plus de la moitie des clients au-dessus du seuil.
Corrigee dans le pitch le jour meme.

#### Trente questions au lieu de dix — `resultats/e2_trente_questions/`

Memes 20 entites, meme population, meme k, meme budget. Seule la longueur de
la trace change : 15 sessions de 2 requetes au lieu de 5.

| Configuration | S_T 10 q | S_T 30 q | sous k 30 q | emises | violations |
|---|---|---|---|---|---|
| Gabarit et budget par session | 100,5 | **27,5** | 75 % | 25,90 | **95 %** |
| Gabarit par session, budget par entite | 100,5 | **27,5** | 75 % | 3,55 | 15 % |
| Gabarit et budget par entite | 121,5 | **121,5** | 0 % | 11,50 | 0 % |

S_T et « sous k » en mode a effort constant, le reste en mode reel, selon la
convention posee plus haut.

**La prediction ecrite avant la mesure est verifiee.** Le pitch annoncait que
les deux premieres lignes empireraient et que la troisieme ne pourrait pas
bouger. C1 passe de 100,5 a 27,5, donc sous le seuil k = 50 : l'entite est
reidentifiee. C3 rend 121,5 dans les deux campagnes, au chiffre pres, et en
mode reel 135,0 dans les deux — identique quel que soit le mode de lecture,
alors que le nombre de requetes emises double, 5,50 puis 11,50.

**Le rang 10 de la campagne a 30 questions vaut 100,5**, exactement le S_T de
la campagne a 10 questions. Les deux campagnes coincident sur leur partie
commune : l'effondrement de C1 se produit entre la dixieme et la trentieme
question, pas avant.

**La mediane de t\* n'est pas comparable entre les deux campagnes.** Elle
passe de 6,5 a 12 pour C1, ce qui se lirait a tort comme une reidentification
plus tardive. Le denominateur a change : 20 % des entites franchissaient le
seuil a 10 questions, 65 % a 30. Les entites ajoutees franchissent tard et
tirent la mediane vers le haut. Seules `part_franchissement` et S_T se
comparent d'une campagne a l'autre.

**Ce que la campagne ne dit pas.** Elle ne valide pas le chiffre de trente : il
n'y a toujours aucun releve du nombre de questions reellement posees sur un
dossier. Elle etablit le sens de la dependance et l'insensibilite de C3, pas
une valeur de terrain.

Les valeurs de |S_T| sont des medianes sur vingt entites, donc des
demi-entiers. Elles ont un temps ete imprimees en entier par un format
d'affichage `:.0f` : les valeurs 100, 122 et 150 qui ont circule sont des
arrondis de 100,5, 121,5 et 149,5 et ne doivent pas etre citees. Deux modes sont necessaires : les configurations s
arretent a des instants differents, et comparer des trajectoires
interrompues a des rangs differents ne mesure rien.

### E7 — detecteurs, Synthea (300 patients, 2712 occurrences, anglais)

Source : `resultats/e7-masquage-20260901-185335-c71e67c5/e7_masquage.json`.
Modele `en_core_web_lg` pour les deux moteurs, la langue etant passee
explicitement. CamemBERT n'est pas mesure ici : il est francophone.

| Moteur | Rappel | Precision | F1 | Debit (car/s) |
|---|---|---|---|---|
| spaCy | 0,8949 | 0,8348 | 0,8638 | 5 886 |
| Presidio | 0,8691 | 0,8328 | 0,8506 | 2 928 |

Comptes bruts, sur 2712 occurrences de reference :

| Moteur | Vrais positifs | Faux negatifs | Faux positifs | Detections | Duree (s) |
|---|---|---|---|---|---|
| spaCy | 2427 | 285 | 340 | 2058 | 12,56 |
| Presidio | 2357 | 355 | 337 | 2016 | 25,25 |

Ecart de rappel : +0,0258, soit +2,97 % en relatif. Rapport de debit : 2,01.

**La valeur de +12,6 % qui a circule est fausse.** Elle vient de l'execution
`e7-masquage-20260901-003304`, anterieure au correctif de normalisation des
etiquettes, ou le rappel de Presidio etait mesure a 0,7946. Elle figure encore
dans des documents de travail ; elle ne doit apparaitre nulle part dans le
memoire.

Le diagnostic est certain, et pas seulement plausible. Entre l'execution de
00:33 et celle de 13:17 le meme jour, le rappel de spaCy ne bouge pas d'un
millieme, 0,8949 dans les deux, tandis que celui de Presidio passe de 0,7946 a
0,8691 et que ses faux positifs passent de 332 a 337. Seul le moteur dont les
etiquettes n'etaient pas reconnues a change. C'est exactement ce que predit un
correctif portant sur la table de normalisation, et rien d'autre ne l'explique.
Le meme correctif, le meme jour, redresse la categorie ORGANISATION d'E7b.

**Piege de relance — la langue.** `run_e7.py` porte `--langue` a `fr` par
defaut :

    parseur.add_argument("--langue", default="fr")

alors que les rubriques `identite` de Synthea sont en anglais. La valeur est
transmise telle quelle a `Masqueur(moteur=..., langue=...)`, qui charge
`MODELES_SPACY[langue]` — donc `fr_core_news_lg` sur du texte anglais. Le
calcul aboutit, aucune erreur n'est levee, et le rappel s'effondre : le
resultat a toutes les apparences d'une mesure.

La commande de reference porte donc la langue explicitement :

    python scripts\run_e7.py --patients 300 --langue en --moteurs spacy,presidio

Regle de lecture : avant d'expliquer un rappel bas sur E7, verifier le champ
`detecteur.modele` du JSON produit. Il doit valoir `en_core_web_lg` pour
Synthea et `fr_core_news_lg` pour le corpus bancaire. Le meme piege existe en
sens inverse sur E7b.

### E7b — detecteurs, corpus bancaire (1500 notes, 6900 occurrences, francais)

Source : `resultats/e7b-banque-20260902-001726-2e6e9d60/e7b_banque.json`.
Corpus : 1500 notes reparties sur 300 dossiers, 6900 occurrences de
reference pour 2400 chaines distinctes. Modele `fr_core_news_lg` pour spaCy
et pour Presidio, `Jean-Baptiste/camembert-ner` pour CamemBERT.

| Moteur | Rappel | Precision | F1 | Debit (car/s) |
|---|---|---|---|---|
| spaCy | 0,9997 | 0,8968 | 0,9454 | 17 376 |
| CamemBERT | 0,9999 | 0,9870 | 0,9934 | 1 412 |
| Presidio | 0,9988 | 0,8925 | 0,9427 | 9 781 |

Comptes bruts, sur 6900 occurrences de reference :

| Moteur | Vrais positifs | Faux negatifs | Faux positifs | Detections | Duree (s) |
|---|---|---|---|---|---|
| spaCy | 6898 | 2 | 656 | 6355 | 22,26 |
| CamemBERT | 6899 | 1 | 75 | 5785 | 274,06 |
| Presidio | 6892 | 8 | 686 | 6382 | 39,55 |

Ventilation par categorie, rappel avec etiquette exigee. Les attendus comptent
les OCCURRENCES ; la colonne des chaines distinctes est rappelee parce que
c'est elle qui figurait dans les versions anterieures du tableau.

| Categorie | Attendus | Chaines distinctes | spaCy | CamemBERT | Presidio |
|---|---|---|---|---|---|
| CARTE | 300 | 300 | 1,0000 | 1,0000 | 1,0000 |
| IBAN | 900 | 300 | 0,8278 | 0,8900 | 0,8278 |
| IDENTIFIANT | 2100 | 600 | 0,9914 | 0,9986 | 0,9914 |
| LIEU | 600 | 300 | 1,0000 | 1,0000 | 1,0000 |
| ORGANISATION | 600 | 300 | 0,8733 | 0,9967 | 0,8733 |
| PERSONNE | 2400 | 600 | 0,9992 | 0,9271 | 0,9967 |

Trois lectures.

Le rappel global proche de 1,000 n'est pas transposable : le corpus est
engendre a partir de cinq gabarits, avec des noms tires d'une liste courte.
C'est le 0,8949 de Synthea qui mesure la performance sur du texte moins
regulier. Ce qui se transpose, en revanche, c'est l'ecart de PRECISION :
CamemBERT produit 75 faux positifs la ou spaCy en produit 656, pour un debit
douze fois moindre. C'est le compromis que le chapitre 5 rapporte.

CamemBERT domine sur ORGANISATION, 0,9967 contre 0,8733, et cede sur
PERSONNE, 0,9271 contre 0,9992. Les deux modeles ne se departagent donc pas
globalement mais categorie par categorie.

spaCy et Presidio donnent des valeurs identiques partout sauf sur PERSONNE.
C'est attendu : Presidio orchestre ici le meme `fr_core_news_lg`, et seule sa
couche de reconnaisseurs propres introduit une difference.

**L'ecart de 0,127 sur ORGANISATION est resolu, et ce n'etait pas un effet de
seuil.** La table de normalisation des etiquettes connaissait `ORG` mais pas
`ORGANIZATION`, le nom que Presidio emploie : toute organisation detectee par
Presidio etait supprimee en silence, sans qu'aucune erreur ne soit levee. Le
diagnostic a seuil nul du 01/09 (`e7b-banque-20260901-004100`), qui donnait
0,1667, portait sur la meme configuration fautive et n'infirme rien. Apres
correctif, Presidio et spaCy rappellent tous deux 0,8733 sur cette categorie.

La lecon generale merite d'etre gardee : une comparaison entre outils dont les
vocabulaires d'etiquettes different echoue SILENCIEUSEMENT, et l'absence de
message d'erreur ne vaut pas absence de defaut. Un controle a ete ajoute, qui
signale toute etiquette produite par un detecteur et non couverte par la
table.

### Correctif d appariement du 31/08/2026

evaluer_texte exigeait qu une detection ne soit appariee qu a une seule
entite de reference. Or spaCy detecte « Pieter Marchand » comme un empan
unique la ou la reference porte le prenom et le nom separement : la seconde
etait comptee comme un faux negatif, divisant mecaniquement par deux le
rappel sur les personnes.

Effet du correctif : rappel Synthea de 0,633 a 0,895 ; rappel PERSONNE sur le
corpus bancaire de 0,500 a 0,999. Le calcul des faux positifs est inchange.


### E2b — borne pessimiste, entites deja uniques

Source : `resultats/e2b/resume.json`. Memes parametres que E2 — population
11 538, k = 50, budget 6 bits, 20 entites, 5 sessions de 2 requetes, trace
« progression » — mais les cibles ne sont plus tirees au hasard : ce sont des
entites deja UNIQUES sous le gabarit, c'est-a-dire le pire cas.

| Configuration | S_T | sous k | emises | deficit (bits) | violations |
|---|---|---|---|---|---|
| Gabarit et budget par session | 49,0 | 50 % | 9,55 | 7,231 | 95 % |
| Gabarit par session, budget par entite | 49,0 | 50 % | 3,40 | 0,854 | 20 % |
| Gabarit et budget par entite | 117,0 | 0 % | 5,40 | 0,000 | 0 % |

Meme convention de lecture que pour E2 : S_T et « sous k » relevent du mode a
effort constant, les autres colonnes du mode reel.

Ce que la campagne etablit. La conclusion d'E2 tient sous le pire cas : seule
la troisieme configuration, gabarit ET budget attaches a l'entite, garde un
deficit de comptabilite nul et un taux de violation nul, et c'est la seule ou
aucune entite ne passe sous le seuil. Les deux autres se degradent : le taux
de violation de C1 monte de 80 % a 95 %, et la part d'entites passant sous k
double, de 20 % a 50 %.

La mediane de |S| des la premiere requete vaut 1976,5 pour E2b contre 11 538
pour E2. C'est la consequence du choix des cibles : une entite deja unique est
par construction plus vite isolee.

Rangs medians de franchissement du seuil, `t_etoile_median` : 7,5 pour C1,
5 pour C2 en mode reel, jamais atteint pour C3.

### E6 — routage reflexif

Source : `resultats/e6/e6_routage.json`. 172 cas, seuil de pertinence 0,55,
seuil de completude 0,7, 5 fragments par requete, graine 20260902. La verite
terrain vient de la construction : le label d'un cas est decide par l'endroit
ou se trouve reellement la reponse, et l'evaluateur ne voit jamais ce label.

| Grandeur | Valeur | Calculee sur |
|---|---|---|
| Taux de decision correcte | 0,9651 | les 172 cas |
| Taux de franchissement injustifie | 0,1304 | les 46 cas ou l'interne suffisait |
| Taux de franchissement manque | 0,0000 | les 46 cas ou il fallait sortir |
| Taux d'abstention correcte | 1,0000 | les 40 cas a enrichissement interdit |
| Taux d'abstention indue | 0,0000 | les 132 autres cas |
| Part passee par la correction | 0,7674 | les 172 cas |
| Sorties infructueuses | 1,0000 | les 40 cas ou la reponse est absente |

Ventilation par classe :

| Classe | Cas | Taux correct |
|---|---|---|
| interne | 40 | 1,0000 |
| interne-decrit | 6 | 0,0000 |
| externe | 40 | 1,0000 |
| externe-implicite | 6 | 1,0000 |
| absente | 40 | 1,0000 |
| enrichissement-interdit | 40 | 1,0000 |

Ce que la campagne etablit, et ce qu'elle ne cache pas. Le taux global de
0,9651 est trompeur si on le cite seul : les six erreurs sont toutes de la
meme espece. Elles se lisent dans la matrice de confusion, `interne-decrit ->
enrichir`, six cas sur six. Ce sont les requetes qui DECRIVENT le dossier au
lieu de le nommer ; le routeur ne reconnait pas que l'interne suffit et sort
inutilement. Le taux de franchissement injustifie sur cette seule classe vaut
1,0000.

C'est exactement le mode d'echec qui compte pour ce travail, puisqu'un
franchissement inutile est une exposition gratuite. Les 96,51 % ne doivent
donc jamais etre annonces sans les 6 sur 6.

Deuxieme point a ne pas taire : quand la reponse n'est nulle part, le routeur
sort dans 100 % des cas. Il ne dispose d'aucun signal pour distinguer une
reponse absente d'une reponse externe, puisqu'il ne juge que la couverture
INTERNE. La distinction demanderait d'evaluer le soutien externe apres
recuperation, ce que `decider()` ne fait pas.

### La recuperation EUR-Lex etait defaillante, et c'est corrige le 25/09

**Le constat.** Sur les 40 questions de la classe `externe` d'E6, l'article
demande n'etait rapporte que **8 fois sur 40 au rang 10**. E3 fournit cinq a
dix fragments legitimes : quatre questions sur cinq n'avaient donc pas leur
article sous les yeux du modele. C'est la cause du « regime degenere » d'E3,
ou l'attaque `assertion` reussit 3 fois sur 4 quand l'article est fourni et
0 fois sur 35 sinon.

**Trois causes, et leurs correctifs.**

| Cause | Correctif |
|---|---|
| `_sujets_eurlex` lisait les numeros d'article dans le TEXTE, donc dans les renvois d'un reglement vers un autre : 6 % des sujets designaient un article inexistant | lecture depuis la RUBRIQUE, qui porte l'article auquel le document appartient — `depuis_rubrique=True`, desormais le defaut |
| le numero d'article vit dans la rubrique et l'index BM25 ne lit que `text` : 9 % seulement des documents numerotes contiennent « Article n » dans leur corps | `index.lexical.enrichir_par_rubrique` prefixe chaque pave de son en-tete, « MiFID2 Article 29. » |
| le corpus porte chaque texte en deux langues, 3 041 EN contre 2 987 FR, et chaque doublon anglophone consomme une place | `langues=("FR",)`, plus un index par reglement choisi d'apres la question |

**Effet cumule, mesure sur les memes 40 questions :**

| Configuration | top 5 | top 10 | top 20 |
|---|---|---|---|
| Avant | 15 % | **20 %** | 28 % |
| + en-tete d'article | 48 % | **65 %** | 75 % |
| + francais seul | 52 % | 60 % | 88 % |
| + filtre par reglement | 70 % | **90 %** | 98 % |

**L'enrichissement n'invente rien.** Tout pave d'un article appartient a cet
article, et un lecteur humain voit cet en-tete en haut de la page. On replace
une information deja vraie la ou le moteur peut la lire.

**Deux chiffres de travail ont circule et sont faux.** Le 24/09, cette
analyse annoncait 0 sur 40 au rang 10 et 18 articles inexistants sur 40. Les
deux venaient du meme defaut : un comparateur qui butait sur `AI_Act` contre
`AI Act`. Les valeurs exactes sont 8 sur 40 et 4 sur 40. Le diagnostic tient,
son ampleur etait surestimee.

**Ce que cela ne change pas.** Aucun chiffre publie d'E3 ne bouge : ils
decrivent un systeme interroge sur des questions auxquelles il ne pouvait pas
repondre. Ce que la mesure etablit, c'est POURQUOI il ne pouvait pas.

**Ce que cela debloque.** La campagne d'E3 sur un jeu ancre devient possible,
et elle coute dix fois moins que prevu : l'ancrage se calculant hors ligne, on
pre-selectionne quarante questions ancrees — 200 appels, environ 0,40 $ — au
lieu d'en tirer trois cents en esperant.

### E6 — le seuil de vocabulaire est un curseur, pas une constante

Balayage du 21/09/2026, `resultats/e6_seuil_<s>/`, jeu etendu v2, 195 cas.

| Seuil | Decision correcte | Sortie inutile | Sur les descriptives | Sortie manquee |
|---|---|---|---|---|
| 0,10 | 0,9538 | **0,0351** | 0,1176 | 0,1207 |
| 0,15 | 0,9641 | **0,0351** | 0,1176 | 0,0862 |
| **0,20** | **0,9744** | 0,0526 | 0,1765 | 0,0345 |
| **0,25** (retenu) | **0,9744** | 0,0702 | 0,2353 | 0,0172 |
| 0,30 | 0,9692 | 0,1053 | 0,3529 | 0,0000 |
| 0,35 et 0,40 | 0,9538 | 0,1579 | 0,5294 | 0,0000 |
| 0,50 | 0,9282 | 0,2456 | 0,8235 | 0,0000 |
| 0,65 | 0,9128 | 0,2982 | 1,0000 | 0,0000 |

**Ce que le balayage etablit, et c'est une reponse a l'objection de
calibration.** Le seuil n'est pas une constante posee au petit bonheur : c'est
un curseur entre les deux erreurs, et l'arbitrage est parfaitement monotone.
De 0,10 a 0,65, l'exposition inutile passe de 3,5 % a 29,8 % tandis que les
sorties manquees passent de 12,1 % a 0 %. **Aucun pic suspect a 0,25** : la
courbe est lisse et 0,25 est sur un plateau.

**0,25 n'est pas l'optimum de l'exposition.** A 0,20, la decision correcte est
identique, 0,9744, et l'exposition inutile est strictement plus basse, 0,0526
contre 0,0702, 0,1765 contre 0,2353 sur les descriptives. Le prix est une
sortie manquee de plus, 2 au lieu de 1. C'est un arbitrage assume, pas un
optimum : a enoncer comme tel.

**0,35 et 0,40 donnent exactement les memes valeurs** : aucune requete du jeu
n'a une couverture de vocabulaire dans cet intervalle. C'est une limite de
granularite du jeu, pas une propriete du seuil.

### E6b — abstention par ignorance, et le double seuil

Campagne du 21/09/2026, `scripts/run_e6b.py`, `resultats/e6b_*`.

**Ce que E6 ne mesurait pas.** `e6_routage.py` le dit : l'abstention y est un
interrupteur de disponibilite, pas un jugement reflexif. Le routeur ne
s'abstient que lorsqu'on lui ferme la sortie ; il n'evalue jamais le soutien
externe. Sur les 40 requetes dont la reponse n'est nulle part, il decide donc
de sortir 40 fois sur 40, et E6 compte cela comme correct.

E6b mesure l'autre moitie : **une fois sorti, le systeme reconnait-il qu'il
n'a rien trouve, et se tait-il plutot que d'inventer ?** La difference
d'outillage tient en une ligne : EUR-Lex y est INDEXE, alors que E6 ne s'en
sert que comme verite terrain.

Le jeu est coupe en deux moities, melangees a graine fixe DANS chaque classe.
Le seuil est choisi sur la moitie de calage, mesure sur celle d'epreuve.

| Seuil externe | Calage : se tait / indu / correct | **Epreuve** : se tait / indu / correct |
|---|---|---|
| 0,15 – 0,35 | 55 % / 10–17 % / 83–85 % | 45 % / 13,8 % / 82,5 % |
| **0,45** | **100 % / 17,2 % / 91,8 %** | **100 % / 13,8 % / 93,8 %** |
| 0,55 (seuil interne reutilise) | 100 % / 48,3 % / 82,7 % | 100 % / **51,7 %** / 82,5 % |
| 0,75 | 100 % / 58,6 % / 79,6 % | 100 % / 55,2 % / 81,4 % |

**Le resultat.** Avec deux seuils separes — 0,55 a l'interieur, 0,45 a
l'exterieur — le systeme se tait 100 % du temps quand la reponse n'existe
nulle part, **n'invente jamais**, et ne refuse a tort que 13,8 % des questions
legitimes. 93,8 % de decisions correctes, mesurees sur la moitie que le
reglage n'a jamais vue. Avec un seuil unique : 51,7 % de refus a tort.

**Le seuil transfere.** 0,45 est choisi sur la moitie de calage et reste le
meilleur sur l'autre, ou il fait meme un peu mieux, 13,8 % contre 17,2 %. Le
reglage n'est donc pas flatte par les donnees qui l'ont pose.

**Un piege de decoupe, corrige le jour meme.** La premiere version coupait le
jeu par rang pair/impair. Or `construire_jeu` produit les cas d'une classe en
ALTERNANT ses gabarits : la coupe mettait donc un gabarit entier d'un cote et
l'autre de l'autre. Les deux moities n'etaient pas deux echantillons de la
meme chose. Symptome : 0 % d'abstention d'un cote et 100 % de l'autre AU MEME
SEUIL. Apres melange, les deux moities se suivent a chaque seuil.

**La reserve qui demeure.** Les 40 questions `absente` viennent de DEUX
gabarits seulement. Apres melange, les deux moities les partagent. Ce n'est
plus faux, mais ce n'est pas une validation complete : elle demanderait des
questions ecrites depuis d'autres gabarits.

Figure : `figures/e6b_abstention.png`.

### E1b — apport de l'hybridation

Deux corpus, 200 questions chacun, un tirage par document, graine 42, k = 10,
sans re-classeur.

EnronQA, source `resultats/e1b/e1b_hybridation.json` :

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence mediane (ms) |
|---|---|---|---|---|
| dense | 0,7600 | 0,6788 | 0,6538 | 531,6 |
| lexical | 0,9500 | 0,8478 | 0,8142 | 917,2 |
| fusion | 0,9350 | 0,8064 | 0,7656 | 1 221,5 |

FinQA, source `resultats/e1b_finqa/e1b_hybridation.json` :

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence mediane (ms) |
|---|---|---|---|---|
| dense | 0,3400 | 0,1980 | 0,1582 | 403,9 |
| lexical | 0,4750 | 0,2800 | 0,2253 | 41,8 |
| fusion | 0,4650 | 0,2603 | 0,2045 | 272,3 |

Apport sur le dense seul, tel que le JSON le publie : sur EnronQA, +0,190 pour
le lexical et +0,175 pour la fusion ; sur FinQA, +0,135 et +0,125.

Ce que la campagne etablit. La fusion ne bat le meilleur versant seul sur
aucun des deux corpus. L'ecart de la fusion au lexical vaut -0,0150 sur
EnronQA et -0,0100 sur FinQA, par soustraction des deux valeurs du tableau.
Le chapitre 2 postule la complementarite des deux versants ; sur ces deux
corpus, a poids egaux, elle ne s'observe pas. Un resultat negatif replique est
rapporte tel quel.

L'explication mecanique est celle de la fusion par rangs reciproques : elle
additionne l'inverse du rang dans chaque classement a poids egal, si bien
qu'un versant dont le rappel est inferieur de treize a dix-neuf points
n'apporte que du bruit en tete. Une fusion ponderee est la piste, avec une
reserve : calibrer le poids sur les corpus qui servent a mesurer le gain
reviendrait a ajuster la mesure sur ses propres donnees.

**Le filtre de corpus, et ce qu'il vaut.** Les deux voies doivent chercher
dans le meme vivier. L'index Qdrant porte les sept corpus, un index BM25 n'en
porte qu'un : sans filtre, la voie dense affronterait 422 189 passages quand
la voie lexicale n'en voit que 73 772, et l'ecart mesure melangerait la
qualite de la recuperation et la taille du vivier.

Le filtre est en place depuis le commit `f03a763`, et les deux executions
d'EnronQA en beneficient. Une reserve inscrite ici le 07/09, qui deduisait de
l'absence du champ `corpus` dans les parametres enregistres que la premiere
execution etait anterieure au filtre, etait FAUSSE : seule l'option
`--corpus` a ete ajoutee plus tard, le filtre lui-meme etait deja cable.
L'execution du 08/09, lancee explicitement avec `--corpus enronqa`, reproduit
les trois configurations au dix-millieme pres.

Ce que le filtre change a ete mesure directement, sur les memes 200 questions,
voie dense seule :

| Voie dense sur EnronQA | Rappel@10 |
|---|---|
| sans filtre de corpus | 0,7400 |
| avec filtre de corpus | 0,7600 |

183 classements sur 200 sont strictement identiques. Huit questions seulement
voient un document d'un autre corpus entrer dans leur tete de classement, pour
31 places sur 2 000. Les autres corpus sont trop eloignes semantiquement d'une
question portant sur des courriels d'entreprise pour la polluer souvent.

La lecon vaut d'etre retenue : le filtre est necessaire par rigueur, et son
effet est reel mais faible, +0,0200. Une asymetrie de vivier ne se voit pas
toujours dans les chiffres, ce qui est precisement pourquoi elle doit etre
empechee par construction plutot que detectee apres coup.

La quatrieme configuration, la fusion suivie du re-classement par
cross-encodeur, n'avait pas ete mesuree en septembre : la memoire disponible
n'avait pas suffi a charger le re-classeur. **Elle l'est depuis le 18/09**,
sur les trois corpus mesurables. Voir ci-dessous.

#### E1b complet — les quatre configurations, trois corpus, 17-18/09/2026

Memes parametres que ci-dessus, 200 questions, graine 42, k = 10, mais avec
le cross-encodeur `BAAI/bge-reranker-v2-m3` charge, sur CPU, profondeur de
re-classement 20.

EnronQA, source `resultats/e1b_complet/e1b_hybridation.json` :

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence mediane (ms) |
|---|---|---|---|---|
| dense | 0,7600 | 0,6788 | 0,6538 | 278,1 |
| lexical | 0,9500 | 0,8478 | 0,8142 | 762,9 |
| fusion | 0,9350 | 0,8064 | 0,7656 | 949,2 |
| complet | 0,9400 | 0,8506 | 0,8224 | **57 242,5** |

FinQA, source `resultats/e1b_finqa_complet/e1b_hybridation.json` :

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence mediane (ms) |
|---|---|---|---|---|
| dense | 0,3400 | 0,1980 | 0,1582 | 244,1 |
| lexical | 0,4750 | 0,2800 | 0,2253 | 62,8 |
| fusion | 0,4650 | 0,2603 | 0,2045 | 279,7 |
| complet | **0,4950** | **0,3103** | **0,2565** | 51 987,6 |

Banque, source `resultats/e1b_banque_complet/e1b_hybridation.json`. **Ces
quatre lignes ne mesurent pas la recuperation** : voir le defaut `aml`
ci-dessous.

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence mediane (ms) |
|---|---|---|---|---|
| dense | 0,8150 | 0,6861 | 0,6420 | 370,3 |
| lexical | 0,8150 | 0,7780 | 0,7650 | 9,6 |
| fusion | 0,8150 | 0,7621 | 0,7439 | 391,6 |
| complet | 0,8150 | 0,7829 | 0,7717 | 13 290,4 |

**Ce que la campagne etablit — premier point, la condition de la fusion.** Le
resultat negatif de septembre se replique et se precise. La fusion ne bat le
meilleur versant seul sur aucun des trois corpus, ni en rappel, ni en nDCG, ni
en MRR. Mais l'ampleur de la perte suit l'ecart entre les deux versants :

| Corpus | Ecart dense <-> lexical | Apport de la fusion sur le meilleur versant |
|---|---|---|
| EUR-Lex, 12 questions (section 11, E1b reglementaire) | 0,0000 | +0,0833 |
| Banque | 0,0000 (plafonne) | 0,0000 |
| FinQA | 0,1350 | -0,0100 |
| EnronQA | 0,1900 | -0,0150 |

La complementarite postulee au chapitre 2 n'est donc ni etablie ni infirmee en
general : elle est **conditionnelle**. A poids egaux, la fusion par rangs
reciproques n'apporte que lorsque les deux versants sont de force comparable,
et coute en proportion de leur ecart. Les douze questions reglementaires, ou
dense et lexical valent tous deux 0,9167, sont le seul jeu ou elle gagne.

**Deuxieme point, ce que fait le re-classement.** Il ne ramene aucun document
nouveau, il re-ordonne la tete. Sur FinQA, ce re-ordonnancement suffit a faire
de `complet` la meilleure configuration sur les trois metriques, +0,0200 de
rappel sur le lexical seul. Sur EnronQA il recupere l'essentiel de ce que la
fusion avait perdu et depasse le lexical en qualite de classement — nDCG
0,8506 contre 0,8478, MRR 0,8224 contre 0,8142 — sans retrouver son rappel.

**Troisieme point, et c'est une conclusion d'ingenierie.** Le re-classement
coute **57,2 s par question sur EnronQA et 52,0 s sur FinQA**, sur CPU, contre
0,76 s pour le lexical seul : un facteur 75. Dans la configuration materielle
que defend ce travail — tout en local, aucune API — le cross-encodeur n'est
pas deployable sur processeur. C'est la dependance materielle que
`src/commun/profils.py` a pour role de rendre mesurable, et elle l'est ici.

**Reserve de methode, a reporter au chapitre 5.** Le champ
`apport_sur_dense_seul` publie par le JSON compare la fusion a la voie DENSE.
Or la voie dense est la plus faible des deux sur les quatre jeux : personne ne
la deploierait seule. La comparaison qui engage une decision est l'apport sur
le **meilleur** versant disponible, donnee dans le tableau ci-dessus. Les deux
lectures doivent figurer, la seconde en premier.

#### Le plafond du corpus banque, et sa cause — 18/09/2026

Les quatre configurations rendent EXACTEMENT 0,8150 sur le corpus bancaire.
Verification faite le 18/09 en rejouant les trois configurations rapides et en
comparant les echecs question par question :

| Configuration | Trouve | Rate | Le bon dossier client est-il dans le top-10 ? |
|---|---|---|---|
| dense | 163 / 200 | 37 | 37 / 37 |
| lexical | 163 / 200 | 37 | 37 / 37 |
| fusion | 163 / 200 | 37 | 37 / 37 |

Les trois ensembles d'echecs sont **identiques**, et les 37 echecs sont
**toutes les questions `aml` de l'echantillon** — il y en a exactement 37.
Aucune autre rubrique n'echoue jamais.

La cause est dans `src/ingestion/banque.py`. Le gabarit `aml` etait le seul
des cinq a ne designer le client que par son identifiant de dossier, sans
prenom, nom, ville ni secteur, alors que les questions de cette rubrique
citent le nom et le secteur. Tous les termes discriminants de la question
etaient donc absents de la note attendue et presents dans ses quatre soeurs :
les deux voies classaient les soeurs devant, a l'identique.

**Consequence sur les chiffres publies.** Le 0,8150 est un plafond du jeu de
test, pas une performance de moteur. Il affecte aussi **E5**, qui utilise le
meme corpus, les memes 200 questions et la meme graine : son rappel de
reference `brut` de 0,8150 a k = 10 est le meme 163/200, et le gain quasi nul
de k = 10 a k = 100 sur ce regime, +0,0050, s'explique par le fait que les
notes `aml` ne contiennent aucun mot de la question et ne remontent a aucune
profondeur.

Au niveau du **dossier client** plutot que de la note exacte, les trois
configurations rendent 200/200, soit 1,0000.

Le gabarit a ete corrige le 18/09. La correction n'ajoute aucun tirage
aleatoire : verification faite en memoire, 1 200 notes restent identiques au
caractere pres et 300 notes `aml` changent. Les campagnes banque anterieures a
cette date portent donc sur une version v1 du corpus, et doivent etre
rejouees : E1b banque, E5, E6, E7b. E3 utilise ce corpus comme corpus interne
et n'a pas ete rejoue, ce qui est declare.

#### Corpus bancaire v2 — effet de la correction du gabarit `aml`, 18/09/2026

Le gabarit `aml` a ete corrige le 18/09 (voir ci-dessus). Les quatre campagnes
qui portent sur ce corpus ont ete rejouees le meme jour, memes parametres,
memes graines. Les resultats v1 restent consignes plus haut : ils ne sont pas
effaces, ils sont dates.

**E1b banque** — `resultats/e1b_banque_v2/`

| Configuration | v1 | v2 | nDCG@10 v2 |
|---|---|---|---|
| dense | 0,8150 | 0,9700 | 0,7964 |
| lexical | 0,8150 | **1,0000** | 0,9575 |
| fusion | 0,8150 | **1,0000** | 0,9317 |
| complet | 0,8150 | **1,0000** | **0,9679** |

Le plafond a saute. Le rappel saturant a 1,0000 pour trois configurations sur
quatre, c'est le CLASSEMENT qui departage desormais, et il reproduit l'ordre
observe sur EnronQA et FinQA : la fusion degrade le classement du meilleur
versant (0,9317 contre 0,9575), le re-classement le redresse au-dessus
(0,9679). L'ecart dense/lexical tombe a 0,0300, ce qui place ce corpus tout en
haut du tableau de conditionnalite — et la fusion n'y perd rien en rappel.

**E5** — `resultats/e5_v2/` et `resultats/e5_profondeur_v2/`

| Regime | Rappel@10 v1 | Rappel@10 v2 | Rappel@100 v1 | Rappel@100 v2 |
|---|---|---|---|---|
| brut | 0,8150 | **1,0000** | 0,8200 | **1,0000** |
| masque | 0,0450 | 0,0650 | 0,3950 | 0,5500 |
| generalise-1 | 0,0750 | 0,1050 | 0,4500 | **0,5750** |
| generalise-2 | 0,0450 | 0,0350 | 0,2600 | 0,2400 |

La reference est enfin propre, et les deux conclusions de v1 sont RENFORCEES,
non contredites. Le facteur de recuperation par la profondeur passe de 5 a 9
selon le regime. Et le premier cran de generalisation reste moins couteux que
le masquage, 0,5750 contre 0,5500 : resultat non intuitif, desormais replique
sur deux versions du corpus.

Le cout relatif publie par le JSON a k = 100 : -45,0 % pour le masquage,
-42,5 % au premier cran, -76,0 % au second. Les latences medianes des huit
mesures tiennent entre 186 et 274 ms, sans ordre stable entre k = 10 et
k = 100 : le surcout de la profondeur n'est pas detectable au-dela du bruit.

Le nDCG@100 des regimes proteges s'effondre a 0,129-0,149 contre 0,932 pour la
requete brute. Le classement rendu par le moteur distant n'est plus
exploitable : c'est le post-filtrage local qui fait le travail.

**E6** — `resultats/e6_etendu_v2/`

| Grandeur | v1 | v2 |
|---|---|---|
| Taux de decision correcte | 0,9795 | 0,9744 |
| Franchissement injustifie, toutes classes | 0,0702 | 0,0702 |
| Franchissement injustifie sur `interne-decrit` | 0,2353 | 0,2353 |
| **Franchissement manque** | **0,0000** | **0,0172** |
| Part passee par la correction | 0,7674 | 0,7179 |

**Une regression reelle, et elle est explicable.** Un cas de la classe
`externe-implicite` bascule en `interne` : les notes de vigilance portent
desormais le nom et le secteur du client, donc le corpus interne parait plus
complet, et le routeur juge une fois de trop qu'il n'a pas besoin de sortir.

C'est la meilleure illustration de la regle de mesure posee en 11.0 : un
corpus interne plus riche produit MOINS d'expositions inutiles et PLUS de
reponses incompletes. Les deux erreurs varient en sens inverse. Additionnees
dans une moyenne, elles auraient donne une baisse d'un demi-point et le
mecanisme serait passe inapercu.

**E7b** — `resultats/e7b-banque-20260918-083116-ec779852/`

La reference passe de 6 900 a 7 800 occurrences : exactement les 300 notes
`aml` multipliees par les trois entites ajoutees (nom, ville, secteur).

| Moteur | Noms rates v1 | Noms rates v2 | F1 v1 | F1 v2 |
|---|---|---|---|---|
| spaCy | 2 / 6 900 | 4 / 7 800 | 0,9454 | 0,9503 |
| CamemBERT | 1 / 6 900 | **1 / 7 800** | 0,9934 | 0,9932 |
| Presidio | 8 / 6 900 | **16 / 7 800** | 0,9427 | 0,9474 |

Le classement ne bouge pas et l'ecart se creuse : le detecteur souverain rate
un nom quand Presidio en rate seize, pour huit fois moins de fausses alertes.

**Un effet inattendu, a ne pas confondre avec une regression.** Le rappel de
CamemBERT sur la categorie PERSONNE, en appariement STRICT sur l'etiquette,
chute de 0,927 a 0,781. Son rappel d'ensemble reste pourtant a 0,9999. Les
deux mesures ne comptent pas la meme chose : la ventilation exige que
l'etiquette soit exacte, le rappel d'ensemble se contente de l'empan.
CamemBERT repere donc les noms, mais en etiquette une partie autrement dans
les notes de vigilance, dont la tournure differe des autres rubriques. Pour le
masquage, qui caviarde un empan, c'est sans effet ; pour la generalisation,
qui choisit un gabarit d'apres la categorie, cela en a un. Meme mecanisme que
celui deja consigne pour la ligne IBAN.

**E3 n'a pas ete rejoue.** Ce corpus lui sert de corpus interne, mais ses
questions portent sur des articles reglementaires externes et son resultat
central — le regime degenere, 3/4 contre 0/35 — repose sur la presence ou
l'absence d'articles EUR-Lex, que la correction ne touche pas. Le rejeu
couterait de 0,8 a 1,2 $ et plusieurs heures pour une variation attendue
faible. Les campagnes E3 sont donc declarees comme portant sur le corpus v1.
A rejouer apres la soutenance du 22/09, sur `assertion` et `instruction`
seulement : le verdict de `duplication` ne lit pas la reponse.

### E4 — attribuabilite

Deux executions, 200 questions et 10 fragments par question, soit 2 000
fragments a chaque fois, graine 42, sans generation.

| Execution | Corpus interroge | Fragments | Ruptures | Taux d'integrite |
|---|---|---|---|---|
| `resultats/e4/e4_provenance.json` | non filtre | 2 000 | 0 | 1,0000 |
| `resultats/e4_eurlex/e4_provenance.json` | eurlex | 2 000 | 0 | 1,0000 |

Dans les deux cas, la repartition de profondeur donne 2 000 fragments sur
2 000 adresses aux quatre niveaux. Les questions employees sont celles
d'EnronQA dans les deux executions : elles ne servent qu'a PROVOQUER des
recuperations, la mesure ne portant pas sur la pertinence des resultats mais
sur la survie du lien vers la source entre l'index et la recherche.

Ce que la campagne etablit. La chaine de provenance ne se rompt jamais sur
2 000 fragments rapportes. C'est la menace visee : une perte silencieuse, sans
adversaire actif, qui violerait l'invariant d'attribuabilite sans qu'aucune
alarme ne se declenche.

Ce qu'elle n'etablit pas, et il faut le dire avant qu'on le demande. Le taux a
quatre niveaux vaut 100 % partout, mais sur la plupart des corpus les deux
derniers niveaux sont renseignes sans rien distinguer. Le releve de structure,
`resultats/e4_structure_corpus.json`, donne le nombre de valeurs distinctes du
champ `page` par corpus :

| Corpus | Passages | Pages distinctes | Paves distincts |
|---|---|---|---|
| Synthea | 45 883 | 1 | 4 |
| EnronQA | 73 772 | 1 | 5 485 |
| PubMedQA | 273 518 | 1 | 211 269 |
| FinQA | 7 134 | 1 | 6 |
| TAT-QA | 14 354 | 1 | 30 |
| EUR-Lex | 6 028 | 141 | 148 |
| Banque | 1 500 | 1 | 5 |

Un seul corpus sur sept exerce reellement le niveau page. Sur les six autres,
le taux constate que les champs sont remplis, ce qui est necessaire mais pas
suffisant, et trois niveaux sont le maximum atteignable. Ce n'est pas une
defaillance d'ingestion : un courriel, un resume d'article ou une note de
dossier n'ont pas de pagination native.

La seconde moitie de la mesure, la part des assertions PRODUITES qui sont
rattachees a un pave, n'est pas faite : le champ `attribuabilite` vaut `null`
dans les deux fichiers. Elle exige un modele de langue configure et s'active
par `--avec-generation`.

### E5 — cout de la protection

Corpus bancaire, 200 questions, graine 42, masquage par spaCy, population
d'entites `data/banque/banque_entites.json`. Quatre regimes : requete brute,
requete masquee, et deux crans de generalisation, le premier remplacant la
ville par sa region, le second remontant au pays et effacant le secteur.

A k = 10, source `resultats/e5/e5_cout.json` :

| Regime | Rappel@10 | nDCG@10 | Longueur mediane (mots) | Latence mediane (ms) |
|---|---|---|---|---|
| brut | 0,8150 | 0,7621 | 19 | 283,9 |
| masque | 0,0450 | 0,0251 | 18 | 304,9 |
| generalise-1 | 0,0750 | 0,0314 | 20 | 345,9 |
| generalise-2 | 0,0450 | 0,0239 | 18 | 342,9 |

A k = 100, source `resultats/e5_profondeur/e5_cout.json` :

| Regime | Rappel@100 | nDCG@100 | Latence mediane (ms) |
|---|---|---|---|
| brut | 0,8200 | 0,7630 | 380,9 |
| masque | 0,3950 | 0,0951 | 371,5 |
| generalise-1 | 0,4500 | 0,1127 | 300,1 |
| generalise-2 | 0,2600 | 0,0615 | 320,1 |

Cout relatif par rapport a la requete brute, tel que le JSON le publie. A
k = 10 : -94,48 % pour le masquage, -90,80 % au premier cran, -94,48 % au
second. A k = 100 : -51,83 %, -45,12 % et -68,29 %.

Ce que la campagne etablit. Mesurer a k = 10 seulement ne dirait qu'une
tautologie : une requete elargie ne designe plus un document unique, ce qui
est le but de la protection. C'est le passage de k = 10 a k = 100 qui donne le
vrai cout. La requete brute ne gagne que 0,005 en rappel, parce que la bonne
note etait deja dans les dix premiers resultats. Les requetes protegees, elles,
gagnent un facteur eleve : le rappel du masquage passe de 0,0450 a 0,3950, le
premier cran de generalisation de 0,0750 a 0,4500, le second de 0,0450 a
0,2600. La cible n'a donc pas disparu du classement, elle y est descendue. Le
prix de la protection est une PROFONDEUR de recherche, pas une perte : il faut
rapatrier dix fois plus de resultats et filtrer localement, ce qui est
justement l'endroit sur.

Deux resultats moins attendus. Le premier cran de generalisation coute MOINS
cher que le masquage, 0,4500 contre 0,3950 a k = 100, parce que generaliser
conserve un signal, la region, la ou masquer supprime. Il existe donc un
reglage qui protege l'intention en coutant moins que le masquage des donnees.
Et le second cran coute plus cher que le masquage A CETTE PROFONDEUR, 0,2600
contre 0,3950 : il franchit le seuil ou il ne reste plus assez d'indices pour
chercher. Cette derniere affirmation doit toujours etre enoncee avec son k :
le balayage ci-dessous montre qu'elle cesse d'etre vraie a k = 200, ou les
deux regimes se rejoignent.

Ce qu'il ne faut pas cacher. Meme a k = 100, la generalisation plafonne a
0,4500 contre 0,8200 pour la requete brute : une fois sur deux, la cible n'est
pas dans les cent premiers resultats. Et le nDCG reste bas, 0,1127, donc le
classement rendu par le moteur distant n'est plus exploitable une fois la
requete elargie ; c'est le post-filtrage local qui fait le travail, ce qui est
l'architecture defendue.

Limite du dispositif, a assumer : dans ce corpus, le nom du client est le
principal signal de recherche, si bien que le retirer coute beaucoup. Sur un
corpus ou la question porterait sur un theme plutot que sur une personne, le
cout serait vraisemblablement moindre, et nous ne l'avons pas mesure.

### E5b v2 — la profondeur, sur le corpus corrige

Six executions du 21/09/2026, memes 200 questions, graine 42, memes quatre
regimes, seul k varie. Sources `resultats/e5_profondeur_v2_k<k>/`. Rejeu
integral du balayage v1 apres la correction du gabarit `aml`.

| k | brute | masquee | generalisee cran 1 | generalisee cran 2 |
|---|---|---|---|---|
| 10 | 1,0000 | 0,0650 | **0,1050** | 0,0350 |
| 25 | 1,0000 | 0,1900 | **0,2350** | 0,1050 |
| 50 | 1,0000 | 0,4100 | **0,4550** | 0,1450 |
| 100 | 1,0000 | 0,5500 | **0,5750** | 0,2400 |
| 200 | 1,0000 | 0,6500 | **0,6800** | 0,4650 |
| 500 | 1,0000 | **0,9550** | 0,9200 | 0,9600 |

**Le controle est desormais exact.** La requete non protegee rend 1,0000 a
TOUTES les profondeurs, de 10 a 500. En v1 elle derivait de 0,8150 a 0,9500,
ce qui brouillait la lecture : on ne savait pas si le gain des regimes
proteges venait de la profondeur ou d'un plafond mouvant. Il n'y a plus
d'ambiguite — la requete brute trouve sa cible dans les dix premiers, ou
jamais.

**L'avantage de la generalisation sur le masquage tient sur cinq profondeurs
sur six**, et l'ecart est plus net qu'en v1 : 0,1050 contre 0,0650 a k = 10,
0,2350 contre 0,1900 a k = 25, 0,4550 contre 0,4100 a k = 50, 0,5750 contre
0,5500 a k = 100, 0,6800 contre 0,6500 a k = 200.

**Il s'inverse a k = 500**, 0,9200 contre 0,9550. L'inversion existait deja en
v1, 0,9550 contre 0,9800 : elle est donc reproduite, pas accidentelle. A cette
profondeur les trois regimes proteges sont au-dessus de 0,92 et l'ordre entre
eux n'a plus d'interet pratique — on ramene la moitie du corpus.

**La regle de dimensionnement change, et se simplifie.** Profondeur necessaire
pour atteindre la moitie du rappel de la requete brute, soit 0,500 :

| Regime | v1 | v2 |
|---|---|---|
| generalisee, cran 1 | k = 100 | **k = 100** |
| masquee | k = 200 | **k = 100** |
| generalisee, cran 2 | k = 200 | **entre 200 et 500** |

Le masquage rattrape le premier cran de generalisation : sur le corpus
corrige, cent resultats suffisent aux deux. Le second cran, lui, s'eloigne
nettement — il reste a 0,2400 la ou les autres depassent 0,5500.

**Conclusion pour le chapitre 5.** Le rejeu ne contredit aucune conclusion de
v1 : il les rend plus lisibles. Le controle est plat, l'ecart generalisation
contre masquage est plus franc, et le second cran se detache comme le seul
regime reellement couteux.

### E5b — rappel en fonction de la profondeur de recherche (v1, corpus avant correction)

Six executions du 11/09/2026, memes 200 questions, meme graine 42, memes
quatre regimes, seul k varie. Sources `resultats/e5_profondeur_k<k>/`.
Figure : `figures/e5_courbe_profondeur.pdf`.

| k | brute | masquee | generalisee cran 1 | generalisee cran 2 |
|---|---|---|---|---|
| 10 | 0,8150 | 0,0450 | 0,0750 | 0,0450 |
| 25 | 0,8150 | 0,1250 | 0,1850 | 0,0900 |
| 50 | 0,8150 | 0,2800 | 0,3550 | 0,1650 |
| 100 | 0,8200 | 0,3950 | 0,4500 | 0,2600 |
| 200 | 0,8550 | 0,5300 | 0,5550 | 0,5350 |
| 500 | 0,9500 | 0,9800 | 0,9550 | 0,9950 |

**Ce que six points etablissent et que deux ne pouvaient pas.**

L'avantage de la generalisation sur le masquage n'est pas un accident du
point k = 100. Il est stable sur tout l'intervalle exploitable : 0,1850 contre
0,1250 a k = 25, 0,3550 contre 0,2800 a k = 50, 0,4500 contre 0,3950 a
k = 100, 0,5550 contre 0,5300 a k = 200. Generaliser conserve un signal la ou
masquer supprime, et la repetition sur quatre profondeurs le montre au lieu de
l'affirmer sur un point.

La requete brute est PLATE de k = 10 a k = 100, 0,8150 a 0,8200. C'est le
controle qui valide toute la lecture : elle trouve sa cible dans les dix
premiers resultats ou ne la trouve pas. Les requetes protegees, elles, gagnent
un facteur six a douze sur le meme intervalle.

**La regle de dimensionnement qui en decoule.** Profondeur necessaire pour
atteindre la moitie du rappel de la requete brute :

| Regime | Profondeur |
|---|---|
| generalisee, cran 1 | k = 100 |
| masquee | k = 200 |
| generalisee, cran 2 | k = 200 |

C'est ce qui transforme l'observation « la cible est enfoncee, pas perdue » en
un critere de deploiement. RemoteRAG demontre theoriquement la profondeur
minimale autour d'une requete perturbee ; faute de pouvoir transposer son
mecanisme, qui suppose un service cooperatif et un modele d'embeddings
partage, nous la mesurons.

**Au-dela de k = 200, la mesure sature et ne doit pas etre lue.** Le corpus
bancaire compte 1500 notes : a k = 500 on en ramene le tiers, les quatre
regimes convergent entre 0,9500 et 0,9950, et les regimes proteges depassent
meme la requete brute. L'ecart entre regimes tombe alors a quelques questions
sur 200, ce qui n'est plus interpretable.

L'hypothese d'un vivier de candidats trop etroit pour la requete brute a ete
testee et ecartee : interrogees a n = 600, la requete brute, la requete
masquee et la requete generalisee rendent chacune 600 candidats de score non
nul. Il s'agit bien de la saturation de la metrique, pas d'un artefact de
recuperation. La figure grise cette zone plutot que de la retirer, afin que la
raison soit visible.

**Le classement n'est jamais exploitable, a aucune profondeur.** Le nDCG du
premier cran de generalisation vaut 0,0314 a k = 10 et 0,1754 a k = 500. Une
fois la requete elargie, l'ordre rendu par le moteur distant ne porte plus
d'information utilisable, et c'est le post-filtrage local qui fait le travail.
C'est exactement l'architecture defendue au chapitre 3, et cette mesure en est
la justification empirique.

### Materiel de chaque campagne

Le journal impose que le materiel soit attache a chaque execution, parce que
le role decide de ce que la mesure vaut : au role « developpement », la
qualite est opposable mais ni la latence ni le debit ne le sont.

| Campagne | Execution citee | Materiel | Role |
|---|---|---|---|
| E7 | `e7-masquage-20260901-185335` | instance GPU louee (Scaleway L4-1-24G, PAR-2) | mesure-souveraine |
| E7b | `e7b-banque-20260902-001726` | instance GPU louee (Scaleway L4-1-24G, PAR-2) | mesure-souveraine |
| E6 | `e6-routage-20260902-014837` | instance GPU louee (Scaleway L4-1-24G, PAR-2) | mesure-souveraine |
| E1b | `e1b-hybridation-20260907-190902` et `-194409` | ultraportable de developpement | developpement |
| E4 | `e4-provenance-20260907-192554` et `-200140` | ultraportable de developpement | developpement |
| E5 | `e5-cout-20260907-193534` et `-200752` | ultraportable de developpement | developpement |

Consequence a respecter dans le chapitre 5 : AUCUNE de ces campagnes n'a
tourne sur un materiel opposable. Les debits de E7 et E7b comme les latences
de E1b, E4 et E5 ne se citent que comme ordres de grandeur relatifs entre
configurations mesurees dans la meme execution. La colonne « Role » du
tableau ci-dessus rapporte l'estampille TELLE QU'ELLE FIGURE dans les
fichiers ; pour les trois premieres lignes elle est fausse, et la
sous-section suivante dit pourquoi.

### L'estampille du 31/08 au 02/09 est fausse, et la cause est etablie

Les quatorze executions du 31/08 au 02/09 portent le materiel
« instance GPU louee (Scaleway L4-1-24G, PAR-2) » et le role
« mesure-souveraine ». **C'est faux. Elles ont toutes tourne sur
l'ultraportable de developpement, et leur role est « developpement ».**

Trois constats independants l'etablissent.

`config.materiel_courant()` selectionne le profil par la variable
d'environnement `RAG_MATERIEL` et retombe sur `ultraportable` quand elle est
absente. Cette variable valait `scaleway` dans l'environnement herite du
terminal, et elle n'est posee ni au niveau Machine ni au niveau User : elle
avait donc ete fixee a la main dans une session, ou elle a survecu bien
au-dela de son objet.

Aucune instance n'etait louee a ces dates. La premiere location est du
07/09, et l'unique execution qui la reflete est
`construction-index-20260907-181343`.

Le support de presentation indiquait deja, independamment, que les debits d'E7
venaient d'un ultraportable sans accelerateur, en citant trois valeurs dont
5 886 caracteres par seconde, precisement celle de l'execution
`e7-masquage-20260901-185335` estampillee Scaleway.

**Ce que cela change, et ce que cela ne change pas.** Les rappels, les
precisions et les F1 ne bougent pas d'un millieme : ils sont deterministes et
ne dependent pas du substrat. Ce qui change est le statut des DEBITS de E7 et
E7b, jusqu'ici declares opposables au titre du role « mesure-souveraine ».
Ils ne le sont pas. Sous le role « developpement », un debit se lit comme un
ordre de grandeur relatif entre moteurs mesures dans la meme execution, et
rien de plus. C'est d'ailleurs ce que trois executions d'E7 montrent d'
elles-memes, avec 6 151, 5 669 et 5 886 caracteres par seconde pour des
rappels strictement identiques : le determinisme tient sur ce qui doit
l'etre, et le debit varie de vingt pour cent.

**La regle a appliquer avant toute campagne**, puisque le defaut est
silencieux et qu'aucune trace ne le signale :

    if ($env:RAG_MATERIEL) { "ATTENTION : RAG_MATERIEL = $env:RAG_MATERIEL" }
    else { "profil par defaut : ultraportable" }

Un terminal neuf ne porte pas la variable ; c'est un terminal reutilise qui
la traine. Verifie le 08/09 : le profil par defaut s'applique, les prochaines
executions seront correctement estampillees.

### Ce qui n'est pas mesure a ce jour

| Mesure | Etat | Bloquee par |
|---|---|---|
| E3, robustesse a l'injection | non faite | simulateur d'attaque adaptative absent du depot |
| E1b, configuration « complet » | non faite | memoire insuffisante pour le cross-encodeur |
| E4, part des assertions rattachees | non faite | demande un modele de langue configure |
| Parite materielle | non faite | deux executions estampillees sous `resultats/`, sans mesure |

Neuf campagnes sont mesurees : E1a, E1b, E2, E2b, E4, E5, E6, E7 et E7b.
