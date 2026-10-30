# Refaire soi-même le parcours amélioré sur ce Mac

Cette procédure utilise la version expérimentale 0.2 dans un nouveau travail.
Elle ne remplace pas l'atelier historique ni le résultat de la version 0.1.
Aucun appel de modèle, aucune installation supplémentaire à faire sur ce Mac.
Le XCF est copié temporairement pour lecture et jamais enregistré.

## Étape 1 — vérifier le lanceur

Ouvrir Terminal, puis :

```sh
cd "/path/to/pcb-workbench/app"
./workshop --help
```

Le lanceur doit afficher les commandes `run`, `compare`, `serve`.

## Étape 2 — refaire l'extraction et le calcul

Dans le même Terminal :

```sh
./workshop run --input "/path/to/board.xcf" --layer Original --output "../../outputs/mon-atelier-pcb-01"
```

Attendre le retour de la commande ; le parcours 0.1 prenait environ 17 secondes,
la durée de cette exécution est enregistrée séparément. GIMP n'a pas besoin
d'être ouvert. Ne pas appliquer un second miroir et ne pas exporter Pistes V2
pour cette entrée : le programme choisit le calque nommé Original.

Sur les mêmes fichiers et cette version, résultat attendu : `complete_proposals`,
670 candidats, 662 ancrages, 495 routes strictes, 416 diagnostics. Les nombres
signalent l'exécution complète, pas une validation électrique.

Si le dossier existe déjà, le programme refuse de l'écraser. Choisir
`mon-atelier-pcb-02`, puis utiliser ce même nom dans les étapes suivantes.
En cas d'erreur, conserver le dossier et son `failure.json`.

## Étape 3 — ouvrir son résultat

```sh
./workshop serve "../../outputs/mon-atelier-pcb-01" --port 8878
```

Laisser ce Terminal ouvert. Dans le navigateur : http://127.0.0.1:8878/
Le port 8877 reste associé au résultat précédent. Si 8878 est occupé, choisir
un autre port et adapter le lien ; ne pas arrêter un serveur inconnu.

## Étape 4 — vérifier avant de corriger

Vérifier que le panneau affiche 670 candidats, 495 tracés visibles, 416 diagnostics
et « Moteur prêt ». Désactiver les tracés pour examiner d'abord les candidats.
Activer/désactiver le masque cyan pour comparer les erreurs de matière.
Zoomer sur un détail du haut et un détail du bas ; ne pas accepter de liaison
sur le seul fait qu'elle est dessinée.

La restriction Lab préalable concerne le détecteur de soudures ; le masque cyan
affiché est le masque final proposé pour le routage. Il ne représente pas à lui
seul toutes les étapes intermédiaires.

## Étape 5 — corriger puis enregistrer

Sélectionner **Soudures : choisir / déplacer**. Déplacer une proposition, rejeter
un candidat manifestement faux, ou ajouter une pastille pour une borne manquée.
Les tracés deviennent périmés ; **Recalculer avec ces soudures** les prépare de
nouveau sur le même masque. Les corrections de cuivre peuvent se faire en ligne
manuelle et tronçons, comme décrit dans `PROCEDURE.md`.

Cliquer **Enregistrer** et attendre la confirmation de révision. Recharger pour
vérifier la reprise. Le travail est dans `mon-atelier-pcb-01/workspace.json`,
avec une copie de la sauvegarde précédente. `workspace.initial.json` reste le
témoin du calcul avant correction.

## Étape 6 — vérifier la répétabilité soi-même

Ouvrir un autre Terminal, refaire le `cd` de l'étape 1, puis lancer :

```sh
./workshop run --input "/path/to/board.xcf" --layer Original --output "../../outputs/mon-atelier-pcb-repetition-01"
./workshop compare "../../outputs/mon-atelier-pcb-01" "../../outputs/mon-atelier-pcb-repetition-01"
```

Attendre `equal_useful_outputs: true`. La comparaison utilise le workspace
initial, donc les corrections ultérieures enregistrées ne changent pas ce test.
Une version différente du code ou des dépendances peut produire un autre
résultat : garder la provenance de chaque essai.

Cette copie de guidage contient les chemins exacts du Mac dans ce document ;
elle n'est pas une nouvelle archive à publier. Le conditionnement portable et
la licence restent à revoir avant une publication explicite.
