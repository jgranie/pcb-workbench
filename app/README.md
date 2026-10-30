# Atelier PCB reproductible — prototype 0.11.0

Le prototype importe PNG/XCF et propose les prétraitements WeVisOne depuis
l'app : contour du PCB, puis retrait de l'époxy par section, avec aperçu et
application au seul calque Original-croppé. La roue crantée de chaque action
permet de choisir **2B ou 4B** et ses paramètres. Aucun modèle n'est chargé au
démarrage et Appliquer ne lance aucune détection. Le panneau **Détection soudures**
utilise WeVisOne par 24 sections avec contexte, sur Original ou Original-croppé,
avec paramètres et corrections manuelles. Le panneau **Préparation** conserve
les actions Contour du PCB et Époxy. Voir [le mode d'emploi](docs/WEVISONE.md).

Le panneau **Détection pistes** reprend le balayage CPU historique, les corrections,
les lignes et le suivi entre soudures. Il utilise la préparation et les points
corrigés du travail courant. Voir [les outils de pistes](docs/TRACES.md).

Cette copie expérimentale ajoute la présegmentation automatique Lab **avant**
le repérage des soudures, en conservant le contraste d'Original, et abaisse la
rondeur minimale à 0,05. La version 0.1 et les anciens workspaces sont conservés.
Sur le même Original : 670 candidats, 662 ancrages, 495 tracés stricts et 416
diagnostics ; 411 correspondances avec l'ancienne référence imparfaite.
Ces nombres ne prouvent pas la justesse électrique.

Pour refaire le parcours soi-même : [guide pas à pas](docs/GUIDED_RUN.md).

Ce paquet part d'une seule photo opaque ou du calque nommé **Original** d'un XCF.
Une commande extrait la photo, propose un masque et des soudures, calcule des
tracés puis crée un workspace vierge. Pour ce parcours CPU, aucun LLM, poids de
modèle, service distant ou session GIMP ouverte n'est nécessaire. GIMP 3 installé est requis
seulement pour lire un XCF.

**La reconstruction électrique autonome n'est pas validée.**
La version 0.1 produisait 455 candidats, dont 225 appariés à moins de 16 px avec
les 598 points d'une ancienne référence VLM/manuelle elle-même imparfaite. La
version 0.2 atteint 411 correspondances sur cette même photo de développement.
La répétabilité de la version 0.2 est testée sur l'exemple synthétique ; le
guide permet de la vérifier sur deux extractions indépendantes du vrai XCF.
Les erreurs
de masque imposent encore une revue importante. Ce prototype ne produit pas de
netlist validée et ne remplace pas l'atelier corrigé existant.

## Installation

Versions testées : Python **3.12.2**, Node **26.8.2**, GIMP **3.2.4** (optionnel).
Les fichiers `.python-version` et `.node-version` consignent ces versions ; ils
ne changent pas les programmes de la machine. Des versions différentes peuvent
modifier les résultats et sont consignées dans chaque provenance.

Depuis le dossier décompressé, avec Python 3.12 et Node disponibles :

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
./workshop --help
```

Si `uv` est déjà installé, l'installation équivalente est :

```sh
uv venv --python 3.12.2 .venv
uv pip install --python .venv/bin/python --require-hashes -r requirements.lock
```

Trois dépendances Python sont verrouillées avec leurs empreintes : Pillow 12.0.0,
NumPy 2.2.6 et OpenCV headless 4.12.0.88. Aucun paquet JavaScript à installer.
L'installation utilise le réseau ; les calculs et la revue sont ensuite locaux.

## Premier essai sans photo privée

```sh
./workshop run --input examples/synthetic.png --output results/example-1
./workshop run --input examples/synthetic.png --output results/example-2
./workshop compare results/example-1 results/example-2 --output results/repeatability.json
./workshop serve results/example-1
```

Ouvrir **http://127.0.0.1:8876/**. Ctrl-C arrête uniquement ce serveur de revue.
L'exemple contient un anneau à quatre bornes et une piste séparée à deux bornes.
Les tests vérifient les cinq liaisons et l'absence de liaison entre les deux réseaux.
L'exemple n'est pas représentatif de la texture et des reflets d'une vraie carte.

## Avec une photo ou un XCF

```sh
./workshop run --input /chemin/carte.xcf --layer Original --output results/carte-1
./workshop serve results/carte-1
```

Pour une photo PNG/JPEG équivalente, remplacer simplement `--input` :

```sh
./workshop run --input /chemin/original.png --output results/photo-1
```

Les chemins relatifs sont interprétés depuis le dossier courant. Le dossier de
sortie doit être nouveau : aucune option ne permet d'écraser un travail. Les
sources sont lues et contrôlées par SHA-256 ; GIMP reçoit une copie temporaire et
une configuration séparée avec `--new-instance`. Il n'enregistre jamais le XCF.
Pour GIMP hors du chemin standard : `--gimp /chemin/vers/gimp-console`.

Lire [la procédure complète](docs/PROCEDURE.md), [la méthode et ses limites](docs/METHOD.md)
et [les points de licence](THIRD_PARTY.md) avant d'utiliser une autre carte.
Les [mesures et limites de validation](docs/VALIDATION.md) détaillent l'essai réel.

## Vérifications

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/geometry.test.mjs
```

Les tests portent sur deux réseaux synthétiques distincts, la conservation d'un
cycle, la répétabilité de deux dossiers indépendants, l'intégrité des sources,
le refus d'écrasement et d'une entrée alpha préparée, la détection d'un résultat
altéré, les limites de configuration et les jonctions manuelles.

## Conditionnement local

```sh
.venv/bin/python tools/package.py --output dist/pcb-workshop-repro.zip
```

L'archive contient une liste autorisée de sources, documentation, tests et exemple
synthétique. Elle exclut photos, XCF, résultats privés, environnements, modèles,
logs et caches. Aucun dépôt Git, push, PR ou publication n'est créé par cette
commande. **Aucune licence du projet n'est choisie** : Jean doit la déterminer
avant publication, ainsi que les droits des exemples photographiques éventuels.
