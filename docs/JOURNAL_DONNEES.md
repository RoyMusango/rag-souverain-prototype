# Journal de bord : données expérimentales

Projet : Recherche hybride sécurisée pour un RAG souverain
Auteur : Roy Ebwelle, UMONS / CETIC, stage du 01/07/2026 au 01/10/2026
Dernière mise à jour : 25/09/2026

---

## 1. Environnement d'exécution

| Élément | Valeur |
|---|---|
| Date d'exécution | 03-04/08/2026 |
| Système | Windows, PowerShell |
| Python | 3.11 |
| JDK (Synthea) | Temurin 25.0.4.7 (JAVA_HOME forcé, car le PATH contenait un JRE 1.8) |
| Chemin racine | C:\Dev\rag-souverain |
| Dépôt Git | https://github.com/RoyMusango/rag-souverain (privé) |
| Cache HuggingFace | C:\Dev\hf_cache (hors dépôt) |
| Modèles NER | spaCy en_core_web_lg, fr_core_news_lg |

Note : pas de GPU sur cette machine. Toute l'extraction NER tourne sur CPU,
d'où les durées de la section 6.

---

## 2. Volumes bruts récupérés

| Corpus | Volume brut | Taille disque | Remarques |
|---|---|---|---|
| Synthea | 1165 patients, 18 CSV | ~810 Mo | graine 42, Massachusetts ; première génération, refaite ensuite (voir 5.7) |
| EnronQA | 221 316 lignes, 4 parquet | 0,62 Go | 150 boîtes confirmées |
| FinQA | 8281 paires (train 6251, dev 883, test 1147) | 26,8 Mo | test gardé, non utilisé |
| TAT-QA | 2479 contextes, 14 883 questions | 4,84 Mo | split test non public |
| PubMedQA | 273 518 (labeled 1000, unlabeled 61 249, artificial 211 269) | ~300 Mo | évaluation sur pqa_labeled |
| Sanctions UE | 6239 entrées | 24 Mo | version du 31/07/2026, XML 1.0 |
| EUR-Lex | 4 textes, 8 PDF (FR + EN) | ~11 Mo | RGPD, DORA, AI Act, MiFID II |

---

## 3. Paramètres de génération Synthea

| Paramètre | Valeur |
|---|---|
| Commande | .\run_synthea.bat -p 10000 -s 42 Massachusetts |
| Population demandée | 10000 |
| Graine (-s) | 42 |
| État | Massachusetts |
| Patients obtenus | 11538 |
| Pourquoi plus que demandé | Synthea génère aussi les patients décédés pendant la période simulée (première génération : 1000 vivants + 165 décédés) |
| Export | CSV activé, FHIR désactivé |

---

## 4. Résultats d'ingestion (schéma commun)

| Corpus | Documents | Rubriques | Entités | Entités/doc | Texte moyen | Vides | Filtrés |
|---|---|---|---|---|---|---|---|
| Synthea | 45 883 | 11 538 | 1 547 784 | 33,7 | 3046 car. | 0 | 269 |
| FinQA | 7134 | 2409 | 342 503 | 48,0 | 4028 car. | 0 | 0 |
| TAT-QA | 14 354 | 2479 | 93 656 | 6,5 | 310 car. | 0 | 0 |
| PubMedQA (partiel) | 62 249 | 2 | 962 971 | 15,5 | 1371 car. | 0 | 0 |
| PubMedQA (complet) | 273 518 | 3 | 3 738 641 | 13,7 | 1394 car. | 0 | 0 |
| EUR-Lex (v1, défaillante) | 918 | 25 | 31 902 | 34,8 | 4255 car. | 0 | 0 |
| EUR-Lex (v2, corrigée) | 4393 | 202 | 36 931 | 8,4 | 875 car. | 0 | 3 doublons retirés |
| EnronQA | 73 772 | 150 | 2 159 916 | 29,3 | 2270 car. | 0 | 0 |

Les deux lignes EUR-Lex correspondent à d'anciennes versions de
l'adaptateur. La version actuelle donne 6028 passages (voir 5.8 et la
section E4).

---

## 5. Choix faits à l'ingestion

### 5.1 Correspondance rubrique / page / pavé

| Corpus | rubrique | page | pavé |
|---|---|---|---|
| Synthea | dossier patient (identifiant) | 1 | rang de la section (identité, conditions, observations, médicaments) |
| EnronQA | boîte aux lettres (champ user) | 1 | rang du courriel dans la boîte |
| FinQA | rapport source (champ filename) | 1 | rang du contexte dans le rapport |
| TAT-QA | identifiant de table (uid) | 1 | rang du paragraphe ; le tableau a le pavé 1 |
| PubMedQA | configuration | 1 | rang du résumé |
| EUR-Lex | article du règlement | page du PDF | rang du paragraphe dans l'article |

**Limite connue.** Cinq corpus sur six ont page = 1 : un courriel ou un
résumé d'article n'a pas de pages. Seul EUR-Lex utilise les quatre niveaux de
la chaîne document -> rubrique -> page -> pavé. C'est pour cela qu'EUR-Lex
sert à montrer l'invariant I3, et que la qualité de son découpage compte
autant pour l'expérience E4.

### 5.2 Synthea : limite de taille des rubriques

MAX_LIGNES_PAR_RUBRIQUE = 40 (abandonné ensuite, voir 5.9).

Raison : la rubrique observations peut avoir plusieurs centaines de lignes
par patient (une par mesure clinique). Sans limite, elle donnerait des
documents énormes, qui domineraient l'index et fausseraient la comparaison
entre rubriques. Avec 40 lignes, on garde un contenu clinique représentatif
et une longueur proche des autres corpus (1675 caractères en moyenne, contre
2270 pour EnronQA).

269 rubriques vides ont été retirées : ce sont des patients sans médicament
prescrit (11 269 patients sur 11 538 ont une rubrique medications ; 269, soit
2,3 %, n'en ont pas).

### 5.3 Synthea : nombres à la fin des noms

Synthea ajoute un nombre aux noms pour les rendre uniques (Wallace647
Effertz744). Ces nombres sont retirés du texte à l'ingestion.

Raison : avec ces chaînes, la mesure du rappel du masquage NER serait
faussée, car aucun modèle n'a vu de tels mots à l'entraînement. Le rappel
mesuré serait trop bas et ne vaudrait pas pour un vrai corpus. L'identifiant
patient, absent du texte, garde chaque patient unique.

### 5.4 EnronQA : dédoublonnage

221 316 lignes brutes donnent 73 772 courriels uniques : 147 544 lignes en
double ont été retirées (facteur 3,0).

Raison : chaque courriel apparaît une fois par question posée sur lui. Sans
dédoublonnage par le champ path, chaque courriel serait indexé trois fois en
moyenne et tous les calculs de rappel seraient faux.

Les 528 304 paires question-réponse sont gardées à part, dans
data/enronqa/enronqa_qa.jsonl, en dehors du schéma documentaire.

**Écart à signaler.** L'article annonce 103 638 courriels ; le dédoublonnage
par path en donne 73 772. L'écart (28,8 %) peut venir du filtrage des
courriels réduits à une signature (moins de 40 caractères de corps utile),
ou d'une autre définition de l'unité documentaire par les auteurs. À vérifier
avant de rédiger le chapitre 4, et à mentionner dans tous les cas.

### 5.5 PubMedQA : étiqueté externe

PubMedQA est étiqueté source = "externe" alors que son contenu est fiable.

Raison : il remplace, de façon contrôlée, le web biomédical. La couche
d'isolation (I2) le traite donc comme non fiable. Pour une évaluation
reproductible, un corpus fixe vaut mieux qu'un web qui change.

### 5.6 FinQA et TAT-QA : splits de test exclus

FinQA : le split test (1147 paires) est téléchargé mais pas ingéré, pour
garder une évaluation finale propre.

TAT-QA : les réponses du split test ne sont pas publiques (elles servent au
classement officiel). L'évaluation se fait sur dev seulement. Annoncer des
chiffres « test » serait une erreur facile à repérer.

### 5.7 Nouvelle taille de population Synthea

Première génération : 1000 patients demandés, 1165 obtenus.

Constat : 83,9 % des patients étaient déjà uniques sur la combinaison des
sept quasi-identifiants, avant toute requête. La courbe de |S| aurait
commencé presque à plat : il n'y avait presque pas d'ensemble d'anonymat à
réduire.

Cause : 273 villes et 254 codes postaux pour 1165 patients, soit 4 à 5
patients par valeur en moyenne. La population était trop petite pour autant
de valeurs géographiques.

Correction : nouvelle génération à 10 000 patients, avec la même graine 42.
11 538 patients obtenus. Le nombre de villes du Massachusetts augmente peu
(415 contre 273, soit x1,5 pour une population x9,9), donc les ensembles
d'anonymat sont nettement plus grands : la part de patients uniques passe de
83,9 % à 46,2 %. E2 a de nouveau quelque chose à mesurer.

Option écartée : retirer la ville et le code postal des quasi-identifiants
et ne garder que le comté (14 valeurs). Écartée parce que la généralisation
géographique est justement le mécanisme de protection étudié (section 3.3.3
du rapport). La faire à l'avance reviendrait à mesurer la protection sur des
données déjà protégées.

### 5.8 EUR-Lex : découpage par articles

Adaptateur v1 : 918 documents, 25 rubriques, un document par page.
Cause : le découpage se faisait sur les doubles sauts de ligne, que
pypdf.extract_text() ne produit pas. Le motif d'en-tête d'article n'était
testé qu'en début de page.

Adaptateur v2 (découpage ligne par ligne) : 4681 documents, 755 rubriques,
142 pages distinctes, pavé maximal de 129 dans une rubrique. La chaîne
document -> rubrique -> page -> pavé existe donc vraiment, ce qu'aucun autre
corpus ne permet.

Découpage par texte (relevé du 01/09/2026) :

| Texte | Articles détectés | Attendus |
|---|---|---|
| AI Act EN | 113 | 113 |
| AI Act FR | 113 | 113 |
| DORA EN | 64 | 64 |
| DORA FR | 64 | 64 |
| MiFID II EN | 98 | 97 |
| MiFID II FR | 97 | 97 |
| RGPD EN | 99 | 99 |
| RGPD FR | 99 | 99 |

Lecture : les quatre textes sont maintenant découpés par article dans les
deux langues, à une unité près pour MiFID II EN. Un relevé plus ancien, noté
ici jusqu'au 31/08/2026, donnait 0 article pour le RGPD, DORA et l'AI Act, et
4393 documents pour 202 rubriques. Il venait d'une version plus ancienne de
l'adaptateur et ne correspond plus au schéma actuel. Les versions v3 et v4
(espaces en trop dans les mots, passage à pymupdf) sont décrites en tête de
`src/ingestion/eurlex.py`.

Conséquence pour E4 : la mesure à quatre niveaux n'est plus limitée à
MiFID II. Elle porte sur les quatre textes.

### 5.9 Synthea : choix des observations gardées

Le plafond de départ (40 premières lignes) a été abandonné après étude de la
distribution réelle.

Constat : la rubrique observations compte 358 lignes par patient en médiane,
758 en moyenne, et jusqu'à 26 539. Un plafond de 40 lignes ne gardait le
dossier complet que pour 0,2 % des patients, et même un plafond de 200 lignes
pour 20,4 % seulement. Couper le dossier devenait la règle.

Problème plus grave que le volume : chaque patient a 63 types d'observation
distincts en médiane (99 au p90). Garder les 40 premières lignes par date
gardait des mesures répétées d'une même consultation (taille, poids, tension)
et perdait au moins 23 types cliniques, dont les résultats de laboratoire
les plus utiles. Changer la valeur du plafond n'aurait rien réglé : c'est le
fait de couper au début qui ne convient pas à un dossier médical.

Choix retenu : garder la DERNIÈRE valeur de chaque type d'observation. Raison
clinique : un dossier se lit par ses valeurs à jour, pas par tout
l'historique.

Résultat : 63 lignes gardées en médiane (p90 : 99 ; max : 148), soit 100 %
des types cliniques, et aucune coupure pour la moitié des patients. Taille
de la rubrique : 5206 caractères en médiane, proche de FinQA (4028) et à un
facteur 2,3 d'EnronQA (2270). La normalisation par longueur de BM25 reste
donc équilibrée.

Plus aucun plafond fixe : garder une ligne par type limite déjà la taille
de la rubrique.

### 5.10 Corpus interne bancaire synthétique

Généré par src/ingestion/banque.py, graine 42, 300 dossiers clients.

| Élément | Valeur |
|---|---|
| Notes | 1500 (5 par dossier) |
| Rubriques | 300 (un dossier client) |
| Texte moyen | 258 caractères |
| Entités de vérité terrain | 6900 |
| dont PERSONNE | 2400 |
| dont IDENTIFIANT | 2100 |
| dont IBAN | 900 |
| dont LIEU / ORGANISATION | 600 / 600 |
| dont CARTE | 300 |

Ces valeurs sont celles de la version v1 du corpus. Depuis la correction du
gabarit `aml` (18/09), la vérité terrain compte 7800 occurrences (voir
section 11, « Corpus bancaire v2 »).

Raison : Synthea ne contient aucun identifiant bancaire. Aucune expérience
ne testait donc les reconnaisseurs déterministes de
confidentialite/verrou.py, et on lisait à tort le rappel de E7 comme celui
de toute la chaîne.

Les IBAN respectent le contrôle modulo 97 et les cartes la clé de Luhn. Avec
des identifiants invalides, on mesurerait seulement la reconnaissance de la
forme, et on ne pourrait pas tester plus tard une validation par somme de
contrôle. Le générateur vérifie ses identifiants au lancement.

Vérité terrain : chaque note est écrite à partir d'un enregistrement
structuré. On sait donc exactement quelles chaînes sont sensibles et de
quelle catégorie. Même principe que pour E2 et E7 sur Synthea.

Limite connue : les notes sont courtes (258 caractères contre 2270 pour
EnronQA) et viennent de cinq gabarits. Ce corpus convient pour mesurer le
masquage, qui se fait entité par entité. Il convient moins bien pour mesurer
la recherche : la normalisation par longueur de BM25 n'y joue pas comme sur
de vrais corpus.

---

## 6. Durées observées (CPU seul, sans GPU)

| Étape | Durée |
|---|---|
| Build Synthea (gradlew) | ~15 min (premier build) |
| Génération 1000 patients | ~5 min |
| Téléchargement EnronQA (666 Mo) | variable |
| Ingestion Synthea (4636 docs, première génération) | quelques minutes |
| Ingestion FinQA (7134 docs) | 24 min |
| Ingestion TAT-QA (14 354 docs) | 6 min |
| Ingestion PubMedQA partielle (62 249 docs) | ~1 h |
| Ingestion PubMedQA complète (273 518 docs) | ~5 h |
| Ingestion EnronQA (73 772 docs) | 39 min |

Ces durées expliquent la méthode du chapitre 4 : il faut calculer les
embeddings une fois et les sauvegarder, car tout relancer à chaque essai
prendrait beaucoup trop de temps.

---

## 7. Conformité et licences

| Élément | Valeur |
|---|---|
| NOTICE.md créé | oui, convention TASL |
| Captures de licence archivées | oui, 7 fichiers dans docs/licences/ (04/08/2026) |
| Demande de régularisation EnronQA | À COMPLÉTER (date, URL) |
| Réponse des auteurs | À COMPLÉTER |
| Saisine du DPO CETIC | À COMPLÉTER (date, destinataire) |

---

## 8. Difficultés rencontrées

| Étape | Problème | Solution | Temps perdu |
|---|---|---|---|
| Prérequis | Java 1.8 installé, Synthea demande Java 11 ou plus | Installation de Temurin 25, JAVA_HOME fixé à la main (l'installeur ne le fait pas par défaut) | ~30 min |
| Git | data\external\eurlex créé comme FICHIER au lieu d'un dossier par Move-Item | Suppression, mkdir explicite, nouveau téléchargement d'un PDF | ~15 min |
| TAT-QA | UnicodeDecodeError à la lecture du JSON | open(..., encoding="utf-8") : l'encodage par défaut de Windows est cp1252 | ~5 min |
| Sanctions UE | URL EEAS de la procédure obsolète (404) | Passage au portail data.europa.eu | ~10 min |
| EUR-Lex | Découpage par articles raté (0 à 9 articles trouvés sur 64 à 113 attendus) | Adaptateur v2 : découpage ligne par ligne au lieu de \\n\\n, car pypdf ne produit pas de double saut de ligne. MiFID II est alors bien découpé (98 articles sur 97), mais pas le RGPD, DORA et l'AI Act. Corrigé ensuite en v3 et v4 (voir 5.8) | ~2 h |
| PubMedQA / EnronQA | Extraction NER de plusieurs heures sur CPU | nlp.pipe avec le seul composant ner ; option --sans-artificial pour aller plus vite pendant la mise au point | non mesuré |

Ces difficultés sont reprises au chapitre 4 du mémoire.

---

## 9. Premiers ordres de grandeur (index)

Certaines valeurs restent à compléter.

| Mesure | Valeur | Matériel |
|---|---|---|
| Débit d'embedding BGE-M3 | 0,5 doc/s (769 docs EUR-Lex en 25,9 min) | ultraportable, 4 fils, float32 |
| Débit attendu sur GPU | À COMPLÉTER | instance GPU |
| Taille de l'index Qdrant | À COMPLÉTER | |
| Construction de l'index lexical BM25 | 22 à 30 s pour 73 772 courriels | ultraportable |
| Latence de recherche BM25 | 639 ms médiane, 955 ms p90 | ultraportable, rank_bm25 sans index inversé |
| Latence dense / fusion | À COMPLÉTER | |

Note : la latence BM25 vient d'une implémentation en Python pur, qui
calcule un score pour chacun des 73 772 documents à chaque requête. Elle ne
représente pas un déploiement avec index inversé.

---

## 10. Population d'entités pour E2

| Élément | Valeur |
|---|---|
| Entités (patients) | 11538 |
| Quasi-identifiants retenus | ville, cp, comté, genre, race, ethnie, tranche_age |
| Palier d'âge | 10 ans |
| Date de référence | 2026-08-03 (fixée pour la reproductibilité) |
| Exclus | Id, SSN, DRIVERS, PASSPORT, LAT, LON, INCOME, HEALTHCARE_* |
| Raison de l'exclusion | identifiants directs ou valeurs continues : |S| = 1 tout de suite, la mesure n'aurait aucun intérêt |
| Patients uniques sur la combinaison complète | 5333 sur 11538 (46,2 %) |

Lecture : ce pourcentage est la part des patients déjà ré-identifiables
sans aucune protection. C'est le point de départ de la courbe de |S|.

---

## 11. Résultats des expériences

Relevés du 31/08/2026 au 25/09/2026. Chaque sous-section indique le fichier
de résultats d'où elle vient, dans `resultats/`.

Deux mises en garde valent pour toute la section. Ne pas citer de valeur
d'E7 antérieure au correctif d'appariement du 31/08 : elle est trop basse.
Et toute valeur de E7 ou E7b antérieure au correctif de normalisation des
étiquettes du 01/09 est fausse pour la catégorie ORGANISATION (explication
plus bas).

### 11.0 Conventions de mesure

Trois conventions s'appliquent à toutes les campagnes de détection
ci-dessous. Elles ont été fixées le 01/09/2026, avant les exécutions
rapportées, et s'appliquent de la même façon à E7 et à E7b. Ne pas les
mélanger.

**1. Le dénominateur du rappel est le nombre d'OCCURRENCES.**
`positions_attendues` trouve chaque chaîne sensible dans chaque texte : une
ville citée deux fois compte deux fois. Le nombre de chaînes DISTINCTES
(2121 sur Synthea, 2400 sur le corpus bancaire) est une autre valeur,
publiée à part sous le nom `chaines_distinctes`. Les valeurs 2121 et 2400
qui figuraient avant à côté d'un rappel étaient de faux dénominateurs : les
bons sont 2712 et 6900.

**2. La précision se calcule sur les DÉTECTIONS**, soit
`(detections - faux_positifs) / detections`. L'ancienne formule,
`VP / (VP + FP)`, divisait un nombre d'entités de référence par une somme
qui mélangeait références et détections. Depuis le correctif d'appariement
du 31/08, une détection peut couvrir plusieurs entités de référence, si bien
que `VP` pouvait dépasser le nombre de détections : sur E7, 2427 vrais
positifs pour 2058 détections. L'ancienne formule avantageait donc les
détecteurs qui produisent de longs empans, c'est-à-dire justement la chaîne
souveraine que ce travail défend. Le JSON donne les deux valeurs,
`precision` et `precision_par_reference`, pour garder la trace du
changement ; seule la première est citée dans le rapport.

Effet chiffré du changement, avec le même modèle et les mêmes détections :

| Exécution | precision (détections) | precision_par_reference |
|---|---|---|
| E7 spaCy | 0,835 | 0,877 |
| E7 Presidio | 0,833 | 0,867 |
| E7b spaCy | 0,897 | 0,913 |
| E7b Presidio | 0,892 | 0,903 |

**3. L'appariement exige la bonne catégorie dans le détail par catégorie,
pas au niveau global.** Au niveau global, la question est de savoir si
l'entité a été masquée : une entité masquée avec la mauvaise étiquette ne
sort pas. Dans le tableau par catégorie, l'étiquette fait partie de ce qu'on
mesure (voir `scripts/run_e7_banque.py`).

### E1a : recherche lexicale seule, EnronQA

200 questions tirées au hasard (graine 42) sur 73 772 courriels.

| k | 1 | 3 | 5 | 10 | 20 | 50 |
|---|---|---|---|---|---|---|
| Rappel@k | 0,660 | 0,840 | 0,880 | 0,910 | 0,930 | 0,965 |
| nDCG@k | 0,660 | 0,767 | 0,783 | 0,792 | 0,798 | 0,805 |

MRR 0,757. Pour sept questions sur 200, le bon document n'est dans aucun des
50 premiers résultats.

Validation externe : Ryan et al. obtiennent un rappel@5 de 0,875 avec BM25
sur ce corpus ; nous mesurons 0,880. Sur 200 tirages, l'écart n'est pas
significatif. L'absence d'écart systématique valide la chaîne d'ingestion,
et en particulier l'unité documentaire choisie (73 772 courriels après
dédoublonnage par chemin, contre 103 638 annoncés par la publication).

### E2 : réduction de l'ensemble d'anonymat, Synthea

20 entités, population 11 538, k = 50, budget 6 bits, trace « progression ».

| Configuration | S_T | sous k | envoyées | déficit (bits) | violations |
|---|---|---|---|---|---|
| Gabarit et budget par session | 100,5 | 20 % | 9,60 | 6,565 | 80 % |
| Gabarit par session, budget par entité | 100,5 | 20 % | 3,55 | 0,714 | 15 % |
| Gabarit et budget par entité | 121,5 | 0 % | 5,50 | 0,000 | 0 % |

Source : `resultats/e2_controle/resume.json`, cibles tirées au hasard.

Les colonnes S_T et « sous k » viennent du mode à effort constant, les
autres du mode réel. Il faut les deux modes : en mode réel, les
configurations s'arrêtent à des moments différents, et comparer des traces
coupées à des rangs différents ne mesure rien.

#### Ce que la population protège à elle seule : rien

Mesure directe sur `data/synthea/entities.json`, sans passer par E2.

| Après divulgation de tous les quasi-identifiants | Synthea | Banque |
|---|---|---|
| Population | 11 538 | 300 |
| Quasi-identifiants | 7 | 4 |
| \|S\| médian par personne | **2** | **1** |
| \|S\| moyen | 2,1 | 1,5 |
| Plus grande classe d'équivalence | 13 | 4 |
| Part des personnes seules | 46,2 % | 59,3 % |
| Part des personnes à \|S\| >= 50 | **0 %** | **0 %** |

**La plus grande classe n'est pas l'ensemble d'anonymat de départ.**
Celui-ci vaut N = 11 538, puisque rien n'est encore divulgué : c'est le
premier point de la courbe. Les 13 sont le PLANCHER, le meilleur cas après
divulgation complète. On confond facilement les deux, d'où cette précision.

Conséquence, qui est le point de départ d'E2 : la population ne protège
rien, donc tout ce que mesure la campagne vient de la façon de compter le
budget. Les 121,5 de C3 s'expliquent par l'arrêt de la configuration à
mi-chemin d'une chute qui irait jusqu'à 2.

**Pourquoi E2 ne tourne pas sur le corpus bancaire.** Avec un seul attribut
divulgué, la part des clients encore à \|S\| >= 50 vaut :

| Attribut divulgué | ville | région | secteur | tranche_encours |
|---|---|---|---|---|
| Part à \|S\| >= 50 | **0 %** | 54,0 % | 57,7 % | **0 %** |

Deux des quatre attributs font passer tout le monde sous le seuil dès qu'ils
sont divulgués. Il resterait deux attributs utilisables et une seule
question avant la chute : la campagne mesurerait la taille du corpus, pas la
règle. Synthea a en plus une échelle de généralisation (ville vers comté,
plus tranche d'âge, genre, origine) que les quatre attributs bancaires n'ont
pas.

**Correction du 21/09.** La présentation affirmait que « k = 50 [est]
impossible à satisfaire dès la première question » sur le corpus bancaire.
C'est faux : région et secteur laissent plus de la moitié des clients
au-dessus du seuil. Corrigé dans la présentation le jour même.

#### Trente questions au lieu de dix : `resultats/e2_trente_questions/`

Mêmes 20 entités, même population, même k, même budget. Seule la longueur
de la trace change : 15 sessions de 2 requêtes au lieu de 5.

| Configuration | S_T 10 q | S_T 30 q | sous k 30 q | envoyées | violations |
|---|---|---|---|---|---|
| Gabarit et budget par session | 100,5 | **27,5** | 75 % | 25,90 | **95 %** |
| Gabarit par session, budget par entité | 100,5 | **27,5** | 75 % | 3,55 | 15 % |
| Gabarit et budget par entité | 121,5 | **121,5** | 0 % | 11,50 | 0 % |

S_T et « sous k » en mode à effort constant, le reste en mode réel, comme
plus haut.

**La prévision écrite avant la mesure se vérifie.** La présentation
annonçait que les deux premières lignes empireraient et que la troisième ne
bougerait pas. C1 passe de 100,5 à 27,5, donc sous le seuil k = 50 :
l'entité est ré-identifiée. C3 donne 121,5 dans les deux campagnes, au
chiffre près, et 135,0 en mode réel dans les deux. La valeur ne change pas,
alors que le nombre de requêtes envoyées double (5,50 puis 11,50).

**Au rang 10, la campagne à 30 questions donne 100,5**, exactement le S_T
de la campagne à 10 questions. Les deux campagnes concordent sur leur
partie commune : la chute de C1 se produit entre la dixième et la trentième
question.

**La médiane de t\* ne se compare pas d'une campagne à l'autre.** Elle passe
de 6,5 à 12 pour C1, ce qu'on pourrait lire à tort comme une
ré-identification plus tardive. Mais le dénominateur a changé : 20 % des
entités passaient sous le seuil à 10 questions, 65 % à 30. Les entités en
plus passent sous le seuil tard et tirent la médiane vers le haut. Seuls
`part_franchissement` et S_T se comparent d'une campagne à l'autre.

**Limite.** La campagne ne valide pas le chiffre de trente : on n'a toujours
aucun relevé du nombre de questions vraiment posées sur un dossier. Elle
montre dans quel sens va la dépendance et que C3 n'y est pas sensible. Elle
ne donne pas une valeur de terrain.

Les valeurs de |S_T| sont des médianes sur vingt entités, donc parfois des
demi-entiers. Un format d'affichage `:.0f` les a un temps arrondies : les
valeurs 100, 122 et 150 qui ont été utilisées sont des arrondis de 100,5,
121,5 et 149,5, et ne doivent pas être citées.

### E7 : détecteurs, Synthea (300 patients, 2712 occurrences, anglais)

Source : `resultats/e7-masquage-20260901-185335-c71e67c5/e7_masquage.json`.
Modèle `en_core_web_lg` pour les deux moteurs, la langue étant donnée
explicitement. CamemBERT n'est pas mesuré ici : c'est un modèle
francophone.

| Moteur | Rappel | Précision | F1 | Débit (car/s) |
|---|---|---|---|---|
| spaCy | 0,8949 | 0,8348 | 0,8638 | 5 886 |
| Presidio | 0,8691 | 0,8328 | 0,8506 | 2 928 |

Comptes bruts, sur 2712 occurrences de référence :

| Moteur | Vrais positifs | Faux négatifs | Faux positifs | Détections | Durée (s) |
|---|---|---|---|---|---|
| spaCy | 2427 | 285 | 340 | 2058 | 12,56 |
| Presidio | 2357 | 355 | 337 | 2016 | 25,25 |

Écart de rappel : +0,0258, soit +2,97 % en relatif. Rapport de débit : 2,01.

**Ne pas citer +12,6 %.** Cette valeur vient de l'exécution
`e7-masquage-20260901-003304`, antérieure au correctif de normalisation des
étiquettes, où le rappel de Presidio valait 0,7946. Elle est encore dans des
documents de travail ; elle ne doit apparaître nulle part dans le mémoire.

La cause est sûre. Entre l'exécution de 00:33 et celle de 13:17 le même
jour, le rappel de spaCy ne change pas d'un millième (0,8949 dans les deux),
alors que celui de Presidio passe de 0,7946 à 0,8691 et ses faux positifs
de 332 à 337. Seul le moteur dont les étiquettes n'étaient pas reconnues a
changé. C'est exactement l'effet attendu d'un correctif de la table de
normalisation, et rien d'autre ne l'explique. Le même correctif, le même
jour, répare la catégorie ORGANISATION d'E7b.

**Piège à la relance : la langue.** `run_e7.py` mettait `--langue` à `fr`
par défaut :

    parseur.add_argument("--langue", default="fr")

alors que les rubriques `identite` de Synthea sont en anglais. La valeur
était passée telle quelle à `Masqueur(moteur=..., langue=...)`, qui charge
`MODELES_SPACY[langue]`, donc `fr_core_news_lg` sur du texte anglais. Le
calcul allait au bout, sans erreur, et le rappel s'effondrait : le résultat
ressemblait à une vraie mesure. Depuis, `--langue` est obligatoire.

La commande de référence donne donc la langue :

    python scripts\run_e7.py --patients 300 --langue en --moteurs spacy,presidio

Règle : avant d'expliquer un rappel bas sur E7, vérifier le champ
`detecteur.modele` du JSON. Il doit valoir `en_core_web_lg` pour Synthea et
`fr_core_news_lg` pour le corpus bancaire. Le même piège existe dans l'autre
sens sur E7b.

### E7b : détecteurs, corpus bancaire (1500 notes, 6900 occurrences, français)

Source : `resultats/e7b-banque-20260902-001726-2e6e9d60/e7b_banque.json`.
Corpus : 1500 notes dans 300 dossiers, 6900 occurrences de référence pour
2400 chaînes distinctes. Modèle `fr_core_news_lg` pour spaCy et pour
Presidio, `Jean-Baptiste/camembert-ner` pour CamemBERT.

| Moteur | Rappel | Précision | F1 | Débit (car/s) |
|---|---|---|---|---|
| spaCy | 0,9997 | 0,8968 | 0,9454 | 17 376 |
| CamemBERT | 0,9999 | 0,9870 | 0,9934 | 1 412 |
| Presidio | 0,9988 | 0,8925 | 0,9427 | 9 781 |

Comptes bruts, sur 6900 occurrences de référence :

| Moteur | Vrais positifs | Faux négatifs | Faux positifs | Détections | Durée (s) |
|---|---|---|---|---|---|
| spaCy | 6898 | 2 | 656 | 6355 | 22,26 |
| CamemBERT | 6899 | 1 | 75 | 5785 | 274,06 |
| Presidio | 6892 | 8 | 686 | 6382 | 39,55 |

Détail par catégorie, rappel avec étiquette exigée. Les attendus comptent
les OCCURRENCES ; la colonne des chaînes distinctes est gardée parce que
c'est elle qui figurait dans les anciennes versions du tableau.

| Catégorie | Attendus | Chaînes distinctes | spaCy | CamemBERT | Presidio |
|---|---|---|---|---|---|
| CARTE | 300 | 300 | 1,0000 | 1,0000 | 1,0000 |
| IBAN | 900 | 300 | 0,8278 | 0,8900 | 0,8278 |
| IDENTIFIANT | 2100 | 600 | 0,9914 | 0,9986 | 0,9914 |
| LIEU | 600 | 300 | 1,0000 | 1,0000 | 1,0000 |
| ORGANISATION | 600 | 300 | 0,8733 | 0,9967 | 0,8733 |
| PERSONNE | 2400 | 600 | 0,9992 | 0,9271 | 0,9967 |

Trois remarques.

Le rappel global proche de 1,000 ne vaut pas pour d'autres corpus : les
notes viennent de cinq gabarits, avec des noms tirés d'une liste courte.
C'est le 0,8949 de Synthea qui mesure la performance sur un texte moins
régulier. Ce qui vaut ailleurs, c'est l'écart de PRÉCISION : CamemBERT
produit 75 faux positifs quand spaCy en produit 656, pour un débit douze
fois plus faible. C'est ce compromis que rapporte le chapitre 5.

CamemBERT est meilleur sur ORGANISATION (0,9967 contre 0,8733) et moins bon
sur PERSONNE (0,9271 contre 0,9992). Aucun des deux modèles n'est meilleur
partout : il faut les comparer catégorie par catégorie.

spaCy et Presidio donnent les mêmes valeurs partout sauf sur PERSONNE.
C'est normal : Presidio utilise ici le même `fr_core_news_lg`, et seuls ses
reconnaisseurs propres font la différence.

**L'écart de 0,127 sur ORGANISATION est expliqué : il venait de la table de
normalisation.** Elle connaissait `ORG` mais pas `ORGANIZATION`, le nom
utilisé par Presidio. Toutes les organisations trouvées par Presidio étaient
donc supprimées, sans aucun message d'erreur. Le diagnostic à seuil nul du
01/09 (`e7b-banque-20260901-004100`), qui donnait 0,1667, portait sur la
même configuration erronée et ne change rien à cette conclusion. Après
correctif, Presidio et spaCy ont tous deux un rappel de 0,8733 sur cette
catégorie.

À retenir : quand on compare des outils qui nomment leurs étiquettes
différemment, la comparaison peut échouer SANS MESSAGE, et l'absence
d'erreur ne prouve pas l'absence de défaut. Un contrôle a été ajouté : il
signale toute étiquette produite par un détecteur et absente de la table.

### Correctif d'appariement du 31/08/2026

`evaluer_texte` imposait qu'une détection ne couvre qu'une seule entité de
référence. Or spaCy détecte « Pieter Marchand » comme un seul empan, alors
que la référence a le prénom et le nom séparés : le second était compté
comme faux négatif, ce qui divisait par deux le rappel sur les personnes.

Effet du correctif : rappel Synthea de 0,633 à 0,895 ; rappel PERSONNE sur
le corpus bancaire de 0,500 à 0,999. Le calcul des faux positifs ne change
pas.

### E2b : borne pessimiste, entités déjà uniques

Source : `resultats/e2b/resume.json`. Mêmes paramètres que E2 (population
11 538, k = 50, budget 6 bits, 20 entités, 5 sessions de 2 requêtes, trace
« progression »), mais les cibles ne sont plus tirées au hasard : ce sont des
entités déjà UNIQUES sur les quasi-identifiants bruts, c'est-à-dire le pire
cas.

| Configuration | S_T | sous k | envoyées | déficit (bits) | violations |
|---|---|---|---|---|---|
| Gabarit et budget par session | 49,0 | 50 % | 9,55 | 7,231 | 95 % |
| Gabarit par session, budget par entité | 49,0 | 50 % | 3,40 | 0,854 | 20 % |
| Gabarit et budget par entité | 117,0 | 0 % | 5,40 | 0,000 | 0 % |

Même lecture que pour E2 : S_T et « sous k » viennent du mode à effort
constant, les autres colonnes du mode réel.

Résultat. La conclusion d'E2 tient dans le pire cas. Seule la troisième
configuration, avec gabarit ET budget attachés à l'entité, garde un déficit
de comptage nul et aucune violation. C'est aussi la seule où aucune entité
ne passe sous le seuil. Les deux autres se dégradent : le taux de violation
de C1 passe de 80 % à 95 %, et la part d'entités sous k double, de 20 % à
50 %.

La médiane de |S| dès la première requête vaut 1976,5 pour E2b, contre
11 538 pour E2. C'est l'effet du choix des cibles : une entité déjà unique
est plus vite isolée.

Rangs médians de passage sous le seuil, `t_etoile_median` : 7,5 pour C1, 5
pour C2 en mode réel, jamais atteint pour C3.

### E6 : routage réflexif

Source : `resultats/e6/e6_routage.json`. 172 cas, seuil de pertinence 0,55,
seuil de complétude 0,7, 5 fragments par requête, graine 20260902. La
vérité terrain vient de la construction du jeu : le label d'un cas dépend de
l'endroit où se trouve vraiment la réponse, et l'évaluateur ne voit jamais
ce label.

| Mesure | Valeur | Calculée sur |
|---|---|---|
| Taux de décision correcte | 0,9651 | les 172 cas |
| Taux de franchissement injustifié | 0,1304 | les 46 cas où l'interne suffisait |
| Taux de franchissement manqué | 0,0000 | les 46 cas où il fallait sortir |
| Taux d'abstention correcte | 1,0000 | les 40 cas où l'enrichissement est interdit |
| Taux d'abstention indue | 0,0000 | les 132 autres cas |
| Part passée par la correction | 0,7674 | les 172 cas |
| Sorties sans résultat | 1,0000 | les 40 cas où la réponse est absente |

Détail par classe :

| Classe | Cas | Taux correct |
|---|---|---|
| interne | 40 | 1,0000 |
| interne-decrit | 6 | 0,0000 |
| externe | 40 | 1,0000 |
| externe-implicite | 6 | 1,0000 |
| absente | 40 | 1,0000 |
| enrichissement-interdit | 40 | 1,0000 |

Lecture. Cité seul, le taux global de 0,9651 trompe : les six erreurs sont
toutes du même type. On les voit dans la matrice de confusion :
`interne-decrit -> enrichir`, six cas sur six. Ce sont les requêtes qui
DÉCRIVENT le dossier sans le nommer. Le routeur ne voit pas que l'interne
suffit et sort pour rien. Sur cette classe seule, le taux de franchissement
injustifié vaut 1,0000.

C'est l'erreur qui compte le plus pour ce travail, puisqu'une
sortie inutile expose la requête sans aucun bénéfice. Il ne faut donc jamais
annoncer les 96,51 % sans les 6 sur 6.

Second point : quand la réponse n'existe nulle part, le routeur sort dans
100 % des cas. Il n'a aucun moyen de distinguer une réponse absente d'une
réponse externe, car il ne juge que la couverture INTERNE. Pour les
distinguer, il faudrait juger le soutien externe après la recherche, ce que
`decider()` ne fait pas. E6b mesure ce cas.

### Recherche EUR-Lex : le défaut, et sa correction du 25/09

**Constat.** Sur les 40 questions de la classe `externe` d'E6, l'article
demandé n'était dans les 10 premiers résultats que **8 fois sur 40**. E3
fournit cinq à dix fragments légitimes : pour quatre questions sur cinq, le
modèle n'avait donc pas l'article sous les yeux. C'est la cause du « régime
dégénéré » d'E3, où l'attaque `assertion` réussit 3 fois sur 4 quand
l'article est fourni, et 0 fois sur 35 sinon.

**Trois causes et leurs corrections.**

| Cause | Correction |
|---|---|
| `_sujets_eurlex` lisait les numéros d'article dans le TEXTE, donc aussi dans les renvois vers d'autres règlements : 6 % des sujets désignaient un article qui n'existe pas | lecture dans la RUBRIQUE, qui donne l'article auquel le document appartient : `depuis_rubrique=True`, maintenant par défaut |
| le numéro d'article est dans la rubrique, mais l'index BM25 ne lit que `text` : seulement 9 % des documents numérotés contiennent « Article n » dans leur texte | `index.lexical.enrichir_par_rubrique` ajoute l'en-tête en tête de chaque pavé, par exemple « MiFID2 Article 29. » |
| le corpus contient chaque texte en deux langues (3 041 EN contre 2 987 FR), et chaque doublon anglais prend une place | `langues=("FR",)`, plus un index par règlement, choisi selon la question |

**Effet cumulé, sur les mêmes 40 questions :**

| Configuration | top 5 | top 10 | top 20 |
|---|---|---|---|
| Avant | 15 % | **20 %** | 28 % |
| + en-tête d'article | 48 % | **65 %** | 75 % |
| + français seul | 52 % | 60 % | 88 % |
| + filtre par règlement | 70 % | **90 %** | 98 % |

**L'en-tête ajouté n'invente rien.** Chaque pavé d'un article appartient
bien à cet article, et un lecteur voit cet en-tête en haut de la page. On
met simplement une information vraie là où le moteur peut la lire.

**Deux chiffres de travail étaient faux.** Le 24/09, cette analyse
annonçait 0 sur 40 au rang 10 et 18 articles inexistants sur 40. Les deux
venaient du même défaut : un comparateur qui ne reconnaissait pas `AI_Act`
face à `AI Act`. Les vraies valeurs sont 8 sur 40 et 4 sur 40. Le diagnostic
reste valable, mais son ampleur était exagérée.

**Ce qui ne change pas.** Aucun chiffre publié d'E3 ne bouge : ils décrivent
un système interrogé sur des questions auxquelles il ne pouvait pas
répondre. Cette mesure explique POURQUOI il ne le pouvait pas.

**Ce que cela permet.** On peut maintenant lancer E3 sur un jeu de questions
ancrées, pour dix fois moins cher que prévu : l'ancrage se calcule hors
ligne, donc on choisit d'avance quarante questions ancrées (200 appels,
environ 0,40 $) au lieu d'en tirer trois cents en espérant.

### E6 : le seuil de vocabulaire est un réglage

Balayage du 21/09/2026, `resultats/e6_seuil_<s>/`, jeu étendu v2, 195 cas.

| Seuil | Décision correcte | Sortie inutile | Sur les descriptives | Sortie manquée |
|---|---|---|---|---|
| 0,10 | 0,9538 | **0,0351** | 0,1176 | 0,1207 |
| 0,15 | 0,9641 | **0,0351** | 0,1176 | 0,0862 |
| **0,20** | **0,9744** | 0,0526 | 0,1765 | 0,0345 |
| **0,25** (retenu) | **0,9744** | 0,0702 | 0,2353 | 0,0172 |
| 0,30 | 0,9692 | 0,1053 | 0,3529 | 0,0000 |
| 0,35 et 0,40 | 0,9538 | 0,1579 | 0,5294 | 0,0000 |
| 0,50 | 0,9282 | 0,2456 | 0,8235 | 0,0000 |
| 0,65 | 0,9128 | 0,2982 | 1,0000 | 0,0000 |

**Résultat, qui répond à la question du calibrage.** Le seuil n'a pas été
fixé au hasard : il règle le compromis entre les deux erreurs, et ce
compromis évolue de façon parfaitement régulière. De 0,10 à 0,65,
l'exposition inutile passe de 3,5 % à 29,8 %, pendant que les sorties
manquées passent de 12,1 % à 0 %. **Pas de pic suspect à 0,25** : la courbe
est régulière et 0,25 est sur un plateau.

**0,25 ne minimise pas l'exposition.** À 0,20, la décision correcte est la
même (0,9744) et l'exposition inutile est plus basse : 0,0526 contre 0,0702,
et 0,1765 contre 0,2353 sur les descriptives. En échange, il y a une sortie
manquée de plus, 2 au lieu de 1. C'est un compromis choisi, à présenter
comme tel.

**0,35 et 0,40 donnent exactement les mêmes valeurs** : aucune requête du
jeu n'a une couverture de vocabulaire dans cet intervalle. Cela tient au
jeu, qui n'a aucun cas dans cette zone.

### E6b : abstention quand la réponse n'existe pas, et double seuil

Campagne du 21/09/2026, `scripts/run_e6b.py`, `resultats/e6b_*`.

**Ce qu'E6 ne mesurait pas.** Comme l'indique `e6_routage.py`, le routeur
ne s'abstient que si on lui ferme la sortie : il ne juge jamais le soutien
externe. Sur les 40 requêtes dont la réponse n'existe nulle part, il décide
donc de sortir 40 fois sur 40, et E6 compte cela comme correct.

E6b mesure la suite : **une fois sorti, le système voit-il qu'il n'a rien
trouvé, et se tait-il au lieu d'inventer ?** La différence d'outillage tient
en une ligne : ici EUR-Lex est INDEXÉ, alors qu'E6 s'en sert seulement comme
vérité terrain.

Le jeu est coupé en deux moitiés, mélangées avec une graine fixe DANS chaque
classe. Le seuil est choisi sur la moitié de calage et mesuré sur la moitié
d'épreuve.

| Seuil externe | Calage : se tait / à tort / correct | **Épreuve** : se tait / à tort / correct |
|---|---|---|
| 0,15 à 0,35 | 55 % / 10 à 17 % / 83 à 85 % | 45 % / 13,8 % / 82,5 % |
| **0,45** | **100 % / 17,2 % / 91,8 %** | **100 % / 13,8 % / 93,8 %** |
| 0,55 (seuil interne réutilisé) | 100 % / 48,3 % / 82,7 % | 100 % / **51,7 %** / 82,5 % |
| 0,75 | 100 % / 58,6 % / 79,6 % | 100 % / 55,2 % / 81,4 % |

**Résultat.** Avec deux seuils séparés, 0,55 pour l'interne et 0,45 pour
l'externe, le système se tait 100 % du temps quand la réponse n'existe
nulle part, **n'invente jamais**, et ne refuse à tort que 13,8 % des
questions légitimes : 93,8 % de décisions correctes, mesurées sur la moitié
que le réglage n'a jamais vue. Avec un seul seuil : 51,7 % de refus à tort.

**Le seuil tient sur l'autre moitié.** 0,45 est choisi sur la moitié de
calage et reste le meilleur sur l'autre, où il fait même un peu mieux
(13,8 % contre 17,2 %). Le réglage n'est donc pas favorisé par les données
qui ont servi à le choisir.

**Un piège de découpe, corrigé le jour même.** La première version coupait
le jeu par rang pair/impair. Or `construire_jeu` produit les cas d'une
classe en ALTERNANT ses gabarits : la coupe mettait donc un gabarit entier
d'un côté et l'autre de l'autre. Les deux moitiés ne contenaient pas les
mêmes types de questions. Symptôme : 0 % d'abstention d'un côté et 100 % de
l'autre AU MÊME SEUIL. Après mélange, les deux moitiés donnent des résultats
proches à chaque seuil.

**Limite restante.** Les 40 questions `absente` viennent de DEUX gabarits
seulement. Après mélange, les deux moitiés les partagent. La mesure n'est
plus faussée. Pour une validation complète, il faudrait des questions
écrites à partir d'autres gabarits.

Figure : `figures/e6b_abstention.png`.

### E1b : apport de l'hybridation

Deux corpus, 200 questions chacun, une question par document, graine 42,
k = 10, sans re-classeur.

EnronQA, source `resultats/e1b/e1b_hybridation.json` :

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence médiane (ms) |
|---|---|---|---|---|
| dense | 0,7600 | 0,6788 | 0,6538 | 531,6 |
| lexical | 0,9500 | 0,8478 | 0,8142 | 917,2 |
| fusion | 0,9350 | 0,8064 | 0,7656 | 1 221,5 |

FinQA, source `resultats/e1b_finqa/e1b_hybridation.json` :

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence médiane (ms) |
|---|---|---|---|---|
| dense | 0,3400 | 0,1980 | 0,1582 | 403,9 |
| lexical | 0,4750 | 0,2800 | 0,2253 | 41,8 |
| fusion | 0,4650 | 0,2603 | 0,2045 | 272,3 |

Apport sur le dense seul, tel que le JSON le publie : sur EnronQA, +0,190
pour le lexical et +0,175 pour la fusion ; sur FinQA, +0,135 et +0,125.

Résultat. Sur aucun des deux corpus la fusion ne bat la meilleure voie
seule. L'écart entre la fusion et le lexical vaut -0,0150 sur EnronQA et
-0,0100 sur FinQA (différence des deux valeurs du tableau). Le chapitre 2
fait l'hypothèse que les deux voies se complètent ; sur ces deux corpus, à
poids égaux, on ne l'observe pas. Ce résultat négatif, retrouvé sur deux
corpus, est rapporté tel quel.

Explication : la fusion par rangs réciproques additionne l'inverse du rang
dans chaque classement, à poids égal. Une voie dont le rappel est plus bas
de treize à dix-neuf points n'ajoute donc que du bruit en tête du
classement. Une fusion pondérée serait la piste à suivre, avec une réserve :
régler le poids sur les corpus qui servent à mesurer le gain reviendrait à
ajuster la mesure sur ses propres données.

**Le filtre de corpus, et ce qu'il change.** Les deux voies doivent chercher
dans les mêmes documents. L'index Qdrant contient les sept corpus, un index
BM25 un seul : sans filtre, la voie dense chercherait parmi 422 189 passages
quand la voie lexicale n'en voit que 73 772, et l'écart mesuré mélangerait
la qualité de la recherche et le nombre de documents.

Le filtre est en place depuis le commit `f03a763`, et les deux exécutions
d'EnronQA l'utilisent. Une réserve notée ici le 07/09 était FAUSSE : comme
le champ `corpus` manquait dans les paramètres enregistrés, elle concluait
que la première exécution était antérieure au filtre. En réalité, seule
l'option `--corpus` a été ajoutée plus tard ; le filtre lui-même était déjà
là. L'exécution du 08/09, lancée avec `--corpus enronqa`, retrouve les trois
configurations au dix-millième près.

L'effet du filtre a été mesuré directement, sur les mêmes 200 questions,
voie dense seule :

| Voie dense sur EnronQA | Rappel@10 |
|---|---|
| sans filtre de corpus | 0,7400 |
| avec filtre de corpus | 0,7600 |

183 classements sur 200 sont exactement identiques. Seules huit questions
voient un document d'un autre corpus entrer dans leurs premiers résultats,
pour 31 places sur 2 000. Les autres corpus sont trop éloignés d'une
question sur des courriels d'entreprise pour la perturber souvent.

À retenir : le filtre est nécessaire, et son effet est réel mais faible
(+0,0200). Une différence de taille entre les ensembles de documents ne se
voit pas toujours dans les chiffres. C'est pour cela qu'il faut l'empêcher
dès la conception au lieu d'espérer la repérer après coup.

La quatrième configuration, fusion puis re-classement par cross-encodeur,
n'avait pas été mesurée début septembre : la mémoire disponible ne suffisait
pas pour charger le re-classeur. **Elle l'est depuis le 18/09**, sur les
trois corpus mesurables (voir ci-dessous).

#### E1b complet : les quatre configurations, trois corpus, 17-18/09/2026

Mêmes paramètres que ci-dessus (200 questions, graine 42, k = 10), avec le
cross-encodeur `BAAI/bge-reranker-v2-m3` chargé, sur CPU, profondeur de
re-classement 20.

EnronQA, source `resultats/e1b_complet/e1b_hybridation.json` :

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence médiane (ms) |
|---|---|---|---|---|
| dense | 0,7600 | 0,6788 | 0,6538 | 278,1 |
| lexical | 0,9500 | 0,8478 | 0,8142 | 762,9 |
| fusion | 0,9350 | 0,8064 | 0,7656 | 949,2 |
| complet | 0,9400 | 0,8506 | 0,8224 | **57 242,5** |

FinQA, source `resultats/e1b_finqa_complet/e1b_hybridation.json` :

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence médiane (ms) |
|---|---|---|---|---|
| dense | 0,3400 | 0,1980 | 0,1582 | 244,1 |
| lexical | 0,4750 | 0,2800 | 0,2253 | 62,8 |
| fusion | 0,4650 | 0,2603 | 0,2045 | 279,7 |
| complet | **0,4950** | **0,3103** | **0,2565** | 51 987,6 |

Banque, source `resultats/e1b_banque_complet/e1b_hybridation.json`. **Ces
quatre lignes ne mesurent pas vraiment la recherche** : voir le défaut
`aml` plus bas.

| Configuration | Rappel@10 | nDCG@10 | MRR | Latence médiane (ms) |
|---|---|---|---|---|
| dense | 0,8150 | 0,6861 | 0,6420 | 370,3 |
| lexical | 0,8150 | 0,7780 | 0,7650 | 9,6 |
| fusion | 0,8150 | 0,7621 | 0,7439 | 391,6 |
| complet | 0,8150 | 0,7829 | 0,7717 | 13 290,4 |

**Premier point : dans quel cas la fusion aide.** Le résultat négatif du
début septembre se confirme et se précise. Sur aucun des trois corpus la
fusion ne bat la meilleure voie seule, ni en rappel, ni en nDCG, ni en MRR.
Mais la perte dépend de l'écart entre les deux voies :

| Corpus | Écart dense / lexical | Apport de la fusion sur la meilleure voie |
|---|---|---|
| EUR-Lex, 12 questions réglementaires (`scripts/run_recherche_questions.py`) | 0,0000 | +0,0833 |
| Banque | 0,0000 (plafonné) | 0,0000 |
| FinQA | 0,1350 | -0,0100 |
| EnronQA | 0,1900 | -0,0150 |

L'hypothèse du chapitre 2 n'est donc ni confirmée ni contredite en général :
tout dépend des cas. À poids égaux, la fusion par rangs réciproques n'aide
que si les deux voies sont de force comparable, et elle coûte d'autant plus
que leur écart est grand. Les douze questions réglementaires, où dense et
lexical valent tous deux 0,9167, sont le seul jeu où elle gagne.

**Deuxième point : ce que fait le re-classement.** Il n'ajoute aucun
nouveau document, il réordonne les premiers résultats. Sur FinQA, cela
suffit pour que `complet` soit la meilleure configuration sur les trois
métriques, avec +0,0200 de rappel sur le lexical seul. Sur EnronQA, il
rattrape l'essentiel de ce que la fusion avait perdu et classe mieux que le
lexical (nDCG 0,8506 contre 0,8478, MRR 0,8224 contre 0,8142), sans
retrouver son rappel.

**Troisième point, pratique.** Le re-classement prend **57,2 s par question
sur EnronQA et 52,0 s sur FinQA**, sur CPU, contre 0,76 s pour le lexical
seul : 75 fois plus. Dans la configuration que défend ce travail (tout en
local, aucune API), le cross-encodeur n'est pas utilisable sur processeur.
C'est la dépendance au matériel que `src/commun/profils.py` doit permettre
de mesurer, et elle est mesurée ici.

**Réserve de méthode, à reprendre au chapitre 5.** Le champ
`apport_sur_dense_seul` du JSON compare la fusion à la voie DENSE. Or la
voie dense est la plus faible des deux sur les quatre jeux : personne ne la
déploierait seule. La comparaison utile pour décider est l'apport sur la
**meilleure** voie disponible, donnée dans le tableau ci-dessus. Il faut
citer les deux, la seconde en premier.

#### Le plafond du corpus bancaire, et sa cause (18/09/2026)

Les quatre configurations donnent EXACTEMENT 0,8150 sur le corpus bancaire.
Vérification du 18/09, en rejouant les trois configurations rapides et en
comparant les échecs question par question :

| Configuration | Trouvé | Raté | Le bon dossier client est-il dans le top 10 ? |
|---|---|---|---|
| dense | 163 / 200 | 37 | 37 / 37 |
| lexical | 163 / 200 | 37 | 37 / 37 |
| fusion | 163 / 200 | 37 | 37 / 37 |

Les trois ensembles d'échecs sont **identiques**, et les 37 échecs sont
**toutes les questions `aml` de l'échantillon** (il y en a exactement 37).
Aucune autre rubrique n'échoue.

La cause est dans `src/ingestion/banque.py`. Le gabarit `aml` était le seul
des cinq à ne désigner le client que par son identifiant de dossier, sans
prénom, nom, ville ni secteur, alors que les questions de cette rubrique
citent le nom et le secteur. Les mots utiles de la question manquaient donc
dans la note attendue et se trouvaient dans les quatre autres notes du
dossier : les deux voies classaient ces autres notes devant, de la même
façon.

**Conséquence sur les chiffres publiés.** Le 0,8150 est une limite du jeu de
test, et ne dit rien de la performance du moteur. Cela touche aussi **E5**,
qui utilise le même corpus, les mêmes 200 questions et la même graine : son
rappel de référence `brut` de 0,8150 à k = 10 correspond aux mêmes 163/200.
Le gain presque nul entre k = 10 et k = 100 dans ce régime (+0,0050) vient
de là : les notes `aml` ne contiennent aucun mot de la question et ne
remontent à aucune profondeur.

Si on compte au niveau du **dossier client** au lieu de la note exacte, les
trois configurations donnent 200/200, soit 1,0000.

Le gabarit a été corrigé le 18/09. La correction n'ajoute aucun tirage
aléatoire : vérification faite, 1 200 notes restent identiques au caractère
près et seules les 300 notes `aml` changent. Les campagnes sur le corpus
bancaire antérieures à cette date portent donc sur une version v1 du corpus
et doivent être rejouées : E1b banque, E5, E6, E7b. E3 utilise ce corpus
comme corpus interne et n'a pas été rejoué, ce qui est signalé.

#### Corpus bancaire v2 : effet de la correction du gabarit `aml` (18/09/2026)

Les quatre campagnes sur ce corpus ont été rejouées le jour même, avec les
mêmes paramètres et les mêmes graines. Les résultats v1 restent plus haut,
avec leur date.

**E1b banque**, `resultats/e1b_banque_v2/`

| Configuration | v1 | v2 | nDCG@10 v2 |
|---|---|---|---|
| dense | 0,8150 | 0,9700 | 0,7964 |
| lexical | 0,8150 | **1,0000** | 0,9575 |
| fusion | 0,8150 | **1,0000** | 0,9317 |
| complet | 0,8150 | **1,0000** | **0,9679** |

Le plafond a disparu. Comme le rappel atteint 1,0000 pour trois
configurations sur quatre, c'est maintenant le CLASSEMENT qui les
départage, et on retrouve l'ordre vu sur EnronQA et FinQA : la fusion classe
moins bien que la meilleure voie (0,9317 contre 0,9575), et le re-classement
fait mieux que les deux (0,9679). L'écart dense / lexical tombe à 0,0300, ce
qui place ce corpus en haut du tableau des écarts, et la fusion n'y perd
rien en rappel.

**E5**, `resultats/e5_v2/` et `resultats/e5_profondeur_v2/`

| Régime | Rappel@10 v1 | Rappel@10 v2 | Rappel@100 v1 | Rappel@100 v2 |
|---|---|---|---|---|
| brut | 0,8150 | **1,0000** | 0,8200 | **1,0000** |
| masque | 0,0450 | 0,0650 | 0,3950 | 0,5500 |
| generalise-1 | 0,0750 | 0,1050 | 0,4500 | **0,5750** |
| generalise-2 | 0,0450 | 0,0350 | 0,2600 | 0,2400 |

La référence est enfin propre, et les deux conclusions de v1 sont
RENFORCÉES. Le gain obtenu en allant plus profond passe d'un facteur 5 à un
facteur 9 selon le régime. Et le premier niveau de généralisation coûte
toujours moins que le masquage (0,5750 contre 0,5500) : résultat
contre-intuitif, maintenant retrouvé sur deux versions du corpus.

Coût relatif publié par le JSON à k = 100 : -45,0 % pour le masquage,
-42,5 % au premier niveau, -76,0 % au second. Les latences médianes des huit
mesures vont de 186 à 274 ms, sans ordre stable entre k = 10 et k = 100 : le
surcoût de la profondeur se perd dans le bruit.

Le nDCG@100 des régimes protégés tombe à 0,129-0,149, contre 0,932 pour la
requête brute. Le classement renvoyé par le moteur distant n'est plus
utilisable : c'est le filtrage local après coup qui fait le travail.

**E6**, `resultats/e6_etendu_v2/`

| Mesure | v1 | v2 |
|---|---|---|
| Taux de décision correcte | 0,9795 | 0,9744 |
| Franchissement injustifié, toutes classes | 0,0702 | 0,0702 |
| Franchissement injustifié sur `interne-decrit` | 0,2353 | 0,2353 |
| **Franchissement manqué** | **0,0000** | **0,0172** |
| Part passée par la correction | 0,7674 | 0,7179 |

**Un vrai recul, qui s'explique.** Un cas de la classe `externe-implicite`
passe en `interne` : les notes de vigilance contiennent maintenant le nom et
le secteur du client, le corpus interne paraît plus complet, et le routeur
juge une fois de trop qu'il n'a pas besoin de sortir.

C'est un bon exemple de la raison pour laquelle les deux erreurs restent
séparées : un corpus interne plus riche donne MOINS d'expositions inutiles
et PLUS de réponses incomplètes. Les deux erreurs varient en sens inverse.
Additionnées dans une moyenne, elles auraient donné une baisse d'un
demi-point, et on n'aurait pas vu le mécanisme.

**E7b**, `resultats/e7b-banque-20260918-083116-ec779852/`

La référence passe de 6 900 à 7 800 occurrences : exactement les 300 notes
`aml` multipliées par les trois entités ajoutées (nom, ville, secteur).

| Moteur | Entités ratées v1 | Entités ratées v2 | F1 v1 | F1 v2 |
|---|---|---|---|---|
| spaCy | 2 / 6 900 | 4 / 7 800 | 0,9454 | 0,9503 |
| CamemBERT | 1 / 6 900 | **1 / 7 800** | 0,9934 | 0,9932 |
| Presidio | 8 / 6 900 | **16 / 7 800** | 0,9427 | 0,9474 |

Le classement ne change pas et l'écart se creuse : CamemBERT rate une
entité quand Presidio en rate seize, avec huit fois moins de fausses
alertes.

**Un effet inattendu, qui n'est pas un recul.** Le rappel de CamemBERT sur
la catégorie PERSONNE, avec l'étiquette exigée, passe de 0,927 à 0,781. Son
rappel global reste pourtant à 0,9999. Les deux mesures ne comptent pas la
même chose : le détail par catégorie exige la bonne étiquette, le rappel
global se contente de l'empan. CamemBERT trouve donc bien les noms, mais en
étiquette une partie autrement dans les notes de vigilance, dont la
tournure diffère des autres rubriques. Pour le masquage, qui cache un empan,
cela ne change rien. Pour la généralisation, qui choisit un gabarit selon
la catégorie, cela compte. C'est le même mécanisme que pour la ligne IBAN.

**E3 n'a pas été rejoué.** Ce corpus lui sert de corpus interne, mais ses
questions portent sur des articles réglementaires externes. Son résultat
principal, le régime dégénéré (3/4 contre 0/35), dépend de la présence ou
non d'articles EUR-Lex, que la correction ne touche pas. Rejouer coûterait
de 0,8 à 1,2 $ et plusieurs heures, pour un effet attendu faible. Les
campagnes E3 sont donc déclarées comme portant sur le corpus v1. À rejouer
après la soutenance du 22/09, sur `assertion` et `instruction` seulement :
le verdict de `duplication` ne lit pas la réponse.

### E4 : attribuabilité

Deux exécutions, 200 questions et 10 fragments par question, soit 2 000
fragments à chaque fois, graine 42, sans génération.

| Exécution | Corpus interrogé | Fragments | Ruptures | Taux d'intégrité |
|---|---|---|---|---|
| `resultats/e4/e4_provenance.json` | non filtré | 2 000 | 0 | 1,0000 |
| `resultats/e4_eurlex/e4_provenance.json` | eurlex | 2 000 | 0 | 1,0000 |

Dans les deux cas, les 2 000 fragments ont leurs quatre niveaux d'adresse.
Les questions viennent d'EnronQA dans les deux exécutions : elles servent
seulement à DÉCLENCHER des recherches. On mesure si le lien vers la source
est conservé entre l'index et la recherche ; la pertinence des résultats
n'entre pas en compte.

Résultat. La chaîne de provenance ne se casse jamais sur 2 000 fragments
rapportés. C'est la menace visée : une perte du lien sans attaquant, qui
violerait l'invariant d'attribuabilité sans aucune alerte.

Limite, à dire tout de suite. Le taux à quatre niveaux vaut 100 % partout,
mais sur la plupart des corpus le niveau page est rempli sans rien
distinguer. Le relevé de structure, `resultats/e4_structure_corpus.json`,
donne le nombre de valeurs distinctes du champ `page` par corpus :

| Corpus | Passages | Pages distinctes | Pavés distincts |
|---|---|---|---|
| Synthea | 45 883 | 1 | 4 |
| EnronQA | 73 772 | 1 | 5 485 |
| PubMedQA | 273 518 | 1 | 211 269 |
| FinQA | 7 134 | 1 | 6 |
| TAT-QA | 14 354 | 1 | 30 |
| EUR-Lex | 6 028 | 141 | 148 |
| Banque | 1 500 | 1 | 5 |

Un seul corpus sur sept utilise vraiment le niveau page. Sur les six
autres, le taux montre que les champs sont remplis, ce qui est nécessaire
mais ne suffit pas, et trois niveaux sont le maximum possible. L'ingestion
n'est pas en cause : un courriel, un résumé d'article ou une note de dossier
n'ont pas de pages.

La seconde partie de la mesure, la part des affirmations PRODUITES
rattachées à un pavé, n'est pas faite : le champ `attribuabilite` vaut
`null` dans les deux fichiers. Elle demande un modèle de langue configuré et
s'active avec `--avec-generation`.

### E5 : coût de la protection

Corpus bancaire, 200 questions, graine 42, masquage par spaCy, population
d'entités `data/banque/banque_entites.json`. Quatre régimes : requête brute,
requête masquée, et deux niveaux de généralisation. Le premier remplace la
ville par sa région, le second remonte au pays et retire le secteur.

À k = 10, source `resultats/e5/e5_cout.json` :

| Régime | Rappel@10 | nDCG@10 | Longueur médiane (mots) | Latence médiane (ms) |
|---|---|---|---|---|
| brut | 0,8150 | 0,7621 | 19 | 283,9 |
| masque | 0,0450 | 0,0251 | 18 | 304,9 |
| generalise-1 | 0,0750 | 0,0314 | 20 | 345,9 |
| generalise-2 | 0,0450 | 0,0239 | 18 | 342,9 |

À k = 100, source `resultats/e5_profondeur/e5_cout.json` :

| Régime | Rappel@100 | nDCG@100 | Latence médiane (ms) |
|---|---|---|---|
| brut | 0,8200 | 0,7630 | 380,9 |
| masque | 0,3950 | 0,0951 | 371,5 |
| generalise-1 | 0,4500 | 0,1127 | 300,1 |
| generalise-2 | 0,2600 | 0,0615 | 320,1 |

Coût relatif par rapport à la requête brute, tel que le JSON le publie. À
k = 10 : -94,48 % pour le masquage, -90,80 % au premier niveau, -94,48 % au
second. À k = 100 : -51,83 %, -45,12 % et -68,29 %.

Résultat. Mesurer seulement à k = 10 n'apprendrait rien : une requête
élargie ne désigne plus un document précis, c'est le but de la protection.
C'est le passage de k = 10 à k = 100 qui donne le vrai coût. La requête
brute ne gagne que 0,005 en rappel, parce que la bonne note était déjà dans
les dix premiers résultats. Les requêtes protégées, elles, gagnent beaucoup :
le rappel du masquage passe de 0,0450 à 0,3950, celui du premier niveau de
généralisation de 0,0750 à 0,4500, celui du second de 0,0450 à 0,2600. La
cible n'a donc pas disparu du classement, elle y est descendue. Le prix de
la protection est de devoir chercher plus PROFOND : il faut récupérer dix
fois plus de résultats et filtrer en local, ce qui est l'endroit
sûr.

Deux résultats moins attendus. Le premier niveau de généralisation coûte
MOINS que le masquage (0,4500 contre 0,3950 à k = 100), parce que
généraliser garde une information, la région, alors que masquer la
supprime. Il existe donc un réglage qui protège l'intention en coûtant moins
que le masquage des données. Et le second niveau coûte plus que le masquage
À CETTE PROFONDEUR (0,2600 contre 0,3950) : il ne reste plus assez d'indices
pour chercher. Il faut toujours donner le k avec cette affirmation : le
balayage ci-dessous montre qu'elle n'est plus vraie à k = 200, où les deux
régimes se rejoignent.

Limites. Même à k = 100, la généralisation plafonne à 0,4500, contre 0,8200
pour la requête brute : une fois sur deux, la cible n'est pas dans les cent
premiers résultats. Et le nDCG reste bas (0,1127) : une fois la requête
élargie, le classement renvoyé par le moteur distant n'est plus utilisable.
C'est le filtrage local qui fait le travail, ce qui correspond à
l'architecture défendue.

Limite du dispositif : dans ce corpus, le nom du client est le principal
indice de recherche, donc le retirer coûte cher. Sur un corpus où les
questions porteraient sur un thème plutôt que sur une personne, le coût
serait sans doute plus faible. Nous ne l'avons pas mesuré.

### E5b v2 : la profondeur, sur le corpus corrigé

Six exécutions du 21/09/2026, mêmes 200 questions, graine 42, mêmes quatre
régimes, seul k change. Sources `resultats/e5_profondeur_v2_k<k>/`. C'est le
balayage v1 rejoué entièrement après la correction du gabarit `aml`.

| k | brute | masquée | généralisée niveau 1 | généralisée niveau 2 |
|---|---|---|---|---|
| 10 | 1,0000 | 0,0650 | **0,1050** | 0,0350 |
| 25 | 1,0000 | 0,1900 | **0,2350** | 0,1050 |
| 50 | 1,0000 | 0,4100 | **0,4550** | 0,1450 |
| 100 | 1,0000 | 0,5500 | **0,5750** | 0,2400 |
| 200 | 1,0000 | 0,6500 | **0,6800** | 0,4650 |
| 500 | 1,0000 | **0,9550** | 0,9200 | 0,9600 |

**La référence est maintenant exacte.** La requête non protégée donne
1,0000 à TOUTES les profondeurs, de 10 à 500. En v1, elle allait de 0,8150 à
0,9500, ce qui brouillait la lecture : on ne savait pas si le gain des
régimes protégés venait de la profondeur ou d'un plafond qui bougeait. Plus
de doute maintenant : la requête brute trouve toujours sa cible dans les dix
premiers résultats.

**La généralisation fait mieux que le masquage à cinq profondeurs sur
six**, avec un écart plus net qu'en v1 : 0,1050 contre 0,0650 à k = 10,
0,2350 contre 0,1900 à k = 25, 0,4550 contre 0,4100 à k = 50, 0,5750 contre
0,5500 à k = 100, 0,6800 contre 0,6500 à k = 200.

**L'ordre s'inverse à k = 500** (0,9200 contre 0,9550). L'inversion
existait déjà en v1 (0,9550 contre 0,9800) : elle se reproduit, ce n'est
pas un accident. À cette profondeur, les trois régimes protégés dépassent
0,92 et leur ordre n'a plus d'intérêt pratique : on ramène un tiers du
corpus.

**La règle de dimensionnement change et devient plus simple.** Profondeur
nécessaire pour atteindre la moitié du rappel de la requête brute, soit
0,500 :

| Régime | v1 | v2 |
|---|---|---|
| généralisée, niveau 1 | k = 100 | **k = 100** |
| masquée | k = 200 | **k = 100** |
| généralisée, niveau 2 | k = 200 | **entre 200 et 500** |

Le masquage rattrape le premier niveau de généralisation : sur le corpus
corrigé, cent résultats suffisent aux deux. Le second niveau s'éloigne
nettement : il reste à 0,2400 quand les autres dépassent 0,5500.

**Conclusion pour le chapitre 5.** Le rejeu ne contredit aucune conclusion
de v1 et les rend plus lisibles. La référence est plate, l'écart entre
généralisation et masquage est plus net, et le second niveau se détache
comme le seul régime vraiment coûteux.

### E5b : rappel selon la profondeur de recherche (v1, corpus avant correction)

Six exécutions du 11/09/2026, mêmes 200 questions, même graine 42, mêmes
quatre régimes, seul k change. Sources `resultats/e5_profondeur_k<k>/`.
Figure : `figures/e5_courbe_profondeur.pdf`.

| k | brute | masquée | généralisée niveau 1 | généralisée niveau 2 |
|---|---|---|---|---|
| 10 | 0,8150 | 0,0450 | 0,0750 | 0,0450 |
| 25 | 0,8150 | 0,1250 | 0,1850 | 0,0900 |
| 50 | 0,8150 | 0,2800 | 0,3550 | 0,1650 |
| 100 | 0,8200 | 0,3950 | 0,4500 | 0,2600 |
| 200 | 0,8550 | 0,5300 | 0,5550 | 0,5350 |
| 500 | 0,9500 | 0,9800 | 0,9550 | 0,9950 |

**Ce que montrent six points, et que deux points ne montraient pas.**

L'avantage de la généralisation sur le masquage ne tient pas au seul point
k = 100. Il se retrouve sur tout l'intervalle utile : 0,1850 contre 0,1250 à
k = 25, 0,3550 contre 0,2800 à k = 50, 0,4500 contre 0,3950 à k = 100,
0,5550 contre 0,5300 à k = 200. Généraliser garde une information que le
masquage supprime, et le fait que l'écart se répète sur quatre profondeurs
le montre.

La requête brute est PLATE de k = 10 à k = 100 (0,8150 à 0,8200). C'est
cette référence qui valide toute la lecture : elle trouve sa cible dans les
dix premiers résultats ou ne la trouve pas. Les requêtes protégées, elles,
gagnent un facteur six à douze sur le même intervalle.

**La règle de dimensionnement qui en découle.** Profondeur nécessaire pour
atteindre la moitié du rappel de la requête brute :

| Régime | Profondeur |
|---|---|
| généralisée, niveau 1 | k = 100 |
| masquée | k = 200 |
| généralisée, niveau 2 | k = 200 |

C'est ce qui transforme l'observation « la cible est descendue dans le
classement, elle n'est pas perdue » en critère de déploiement. RemoteRAG
établit en théorie la profondeur minimale autour d'une requête perturbée.
Son mécanisme suppose un service coopératif et un modèle d'embeddings
partagé, et nous ne pouvons pas le reprendre : nous mesurons donc cette
profondeur.

**Au-delà de k = 200, la mesure sature et ne doit pas être lue.** Le corpus
bancaire compte 1500 notes : à k = 500, on en ramène un tiers, les quatre
régimes se rejoignent entre 0,9500 et 0,9950, et les régimes protégés
dépassent même la requête brute. L'écart entre régimes tombe à quelques
questions sur 200, ce qui ne s'interprète plus.

On a testé, et écarté, l'hypothèse d'un ensemble de candidats trop petit
pour la requête brute : interrogées à n = 600, la requête brute, la requête
masquée et la requête généralisée renvoient chacune 600 candidats de score
non nul. C'est donc bien la métrique qui sature. La figure met cette zone en
gris au lieu de la retirer, pour qu'on en voie la raison.

**Le classement n'est utilisable à aucune profondeur.** Le nDCG du premier
niveau de généralisation vaut 0,0314 à k = 10 et 0,1754 à k = 500. Une fois
la requête élargie, l'ordre renvoyé par le moteur distant ne contient plus
d'information utilisable, et c'est le filtrage local qui fait le travail.
C'est l'architecture défendue au chapitre 3, et cette mesure la justifie par
l'expérience.

### Matériel de chaque campagne

Le journal enregistre le matériel avec chaque exécution, parce que le rôle
du matériel décide de ce que vaut la mesure : avec le rôle
« développement », la qualité est valable, mais ni la latence ni le débit.

| Campagne | Exécution citée | Matériel | Rôle |
|---|---|---|---|
| E7 | `e7-masquage-20260901-185335` | instance GPU louée (Scaleway L4-1-24G, PAR-2) | mesure-souveraine |
| E7b | `e7b-banque-20260902-001726` | instance GPU louée (Scaleway L4-1-24G, PAR-2) | mesure-souveraine |
| E6 | `e6-routage-20260902-014837` | instance GPU louée (Scaleway L4-1-24G, PAR-2) | mesure-souveraine |
| E1b | `e1b-hybridation-20260907-190902` et `-194409` | ultraportable de développement | développement |
| E4 | `e4-provenance-20260907-192554` et `-200140` | ultraportable de développement | développement |
| E5 | `e5-cout-20260907-193534` et `-200752` | ultraportable de développement | développement |

Conséquence pour le chapitre 5 : AUCUNE de ces campagnes n'a tourné sur un
matériel dont les mesures de performance sont valables. Les débits de E7 et
E7b, comme les latences de E1b, E4 et E5, se citent seulement comme ordres
de grandeur, pour comparer des configurations mesurées dans la même
exécution. La colonne « Rôle » reprend l'estampille TELLE QU'ELLE EST dans
les fichiers ; pour les trois premières lignes, elle est fausse (voir la
sous-section suivante).

### L'estampille du 31/08 au 02/09 est fausse, et on sait pourquoi

Les quatorze exécutions du 31/08 au 02/09 portent le matériel « instance GPU
louée (Scaleway L4-1-24G, PAR-2) » et le rôle « mesure-souveraine ». **C'est
faux. Elles ont toutes tourné sur l'ultraportable de développement, et leur
rôle est « développement ».**

Trois constats indépendants le montrent.

`config.materiel_courant()` choisit le profil d'après la variable
d'environnement `RAG_MATERIEL`, et prend `ultraportable` si elle n'existe
pas. Cette variable valait `scaleway` dans l'environnement du terminal,
alors qu'elle n'est définie ni au niveau Machine ni au niveau User : elle
avait donc été fixée à la main dans une session, et elle est restée bien
après.

Aucune instance n'était louée à ces dates. La première location date du
07/09, et la seule exécution qui la reflète est
`construction-index-20260907-181343`.

La présentation indiquait déjà, de son côté, que les débits d'E7 venaient
d'un ultraportable sans GPU, en citant trois valeurs dont 5 886 caractères
par seconde, justement celle de l'exécution `e7-masquage-20260901-185335`
estampillée Scaleway.

**Ce qui change, et ce qui ne change pas.** Les rappels, précisions et F1 ne
bougent pas d'un millième : ils sont déterministes et ne dépendent pas de la
machine. Ce qui change, c'est le statut des DÉBITS de E7 et E7b, présentés
jusqu'ici comme valables au titre du rôle « mesure-souveraine ». Ils ne le
sont pas. Avec le rôle « développement », un débit se lit seulement comme un
ordre de grandeur relatif entre moteurs mesurés dans la même exécution.
Trois exécutions d'E7 le montrent d'ailleurs : 6 151, 5 669 et 5 886
caractères par seconde pour des rappels exactement identiques. Ce qui doit
être déterministe l'est, et le débit varie de vingt pour cent.

**La règle à appliquer avant chaque campagne**, puisque le défaut ne se voit
pas et qu'aucune trace ne le signale :

    if ($env:RAG_MATERIEL) { "ATTENTION : RAG_MATERIEL = $env:RAG_MATERIEL" }
    else { "profil par defaut : ultraportable" }

Un terminal neuf n'a pas la variable ; c'est un terminal réutilisé qui la
garde. Vérifié le 08/09 : le profil par défaut s'applique, et les exécutions
suivantes seront bien estampillées.

### Ce qui n'est pas encore mesuré ou consigné

| Mesure | État | Raison |
|---|---|---|
| E3, robustesse à l'injection | résultats non consignés dans ce journal | à compléter (des campagnes ont eu lieu, voir « Recherche EUR-Lex » et « Corpus bancaire v2 ») |
| E4, part des affirmations rattachées | non faite | demande un modèle de langue configuré |
| Parité matérielle | non faite | deux exécutions estampillées sous `resultats/`, sans mesure |

Campagnes mesurées et consignées dans ce journal : E1a, E1b, E2, E2b, E4,
E5 (avec E5b), E6, E6b, E7 et E7b.
