# Refaire un atelier depuis une image

La version 0.2 active la restriction Lab avant les soudures et une rondeur minimale
de 0,05. Utiliser son propre `config.json` : un ancien fichier 0.1 n'a pas la clé
`solder_foreground`. Pour le parcours exact sur le Mac de Jean, voir `GUIDED_RUN.md`.

## 1. Préparer l'entrée une fois

Garder le fichier d'origine. Pour un XCF, connaître le **nom exact** du calque
photographique : le programme refuse zéro ou plusieurs correspondances. Les
indices du XCF, les noms `layer-N.png` et l'ordre d'un ancien éditeur ne sont pas
interchangeables. Les groupes nommés comme la photo sont refusés.

Pour une photo sans GIMP, utiliser un PNG opaque ou un JPEG. Une transparence
existante est refusée : elle pourrait masquer un détourage déjà préparé. Le nom
Original ne certifie pas une photo brute : une transformation ou une retouche
antérieure au XCF reste possible. Le programme extrait le rendu du calque, avec
son opacité, son mode et son éventuel masque consignés dans `extracted.json`.

## 2. Choisir le repère sans doubler une symétrie

La configuration par défaut ne recadre pas, ne retourne pas et ne redresse pas
la perspective. Elle applique l'orientation EXIF, puis seulement les opérations
explicitement demandées : recadrage, quarts de tour horaires, miroir horizontal.
La carte doit être suffisamment cadrée, verte et contrastée. Maximum : 6 Mpx.

Si nécessaire, copier `config.json` en `my-config.json`, puis modifier :

```json
{"crop": [10, 20, 1950, 2750], "rotate_quarters": 0, "mirror_x": false}
```

Ce fragment montre les champs ; le fichier passé à `--config` doit contenir
toutes les clés de `config.json`. Le recadrage s'exprime après orientation EXIF.
Vérifier le sens du texte et les positions de deux détails asymétriques avant de
faire un miroir. Une photo déjà orientée pour la face composants garde
`mirror_x: false`. Aucune valeur en millimètres n'est déduite.

## 3. Exécuter sans anciennes annotations

```sh
./workshop run --input /chemin/carte.xcf --layer Original --config my-config.json --output results/run-a
```

Le pipeline ne possède pas de paramètre permettant d'importer un ancien masque,
des BB de modèle, des corrections ou des coordonnées particulières à une carte.
Il ne lit aucun workspace existant. L'image canonique est `original.png`, sans
métadonnées volatiles ; son empreinte RGBA est dans `image.json`.

Consulter `result.json` : `complete_proposals` signifie que les étapes ont terminé,
pas que la reconstruction est juste. `partial_proposals` signale une limite
atteinte. En cas d'erreur, le dossier conserve `failure.json` et les étapes déjà
produites ; choisir un autre dossier pour réessayer. Ne jamais recycler cet
échec en injectant le masque ou les boîtes de l'ancien travail.

## 4. Examiner et corriger

```sh
./workshop serve results/run-a --port 8876
```

1. Comparer la photo, le masque cyan et les propositions. Les chiffres, trous,
   corps CMS et reflets peuvent être classés à tort. Les pistes masquées restent
   inconnues. Une variante différente peut être calculée dans un autre dossier
   avec `method: "adaptive"` ou `method: "lab-a"` ; aucune n'est une vérité terrain.
2. Dans **Soudures**, choisir/déplacer un candidat ; Cmd/Ctrl/Maj-clic ajoute une
   sélection, **Rejeter la sélection** retire le groupe. Ajouter une pastille au
   centre visible pour une soudure manquée, puis la déplacer. Ces changements
   rendent les tracés automatiques périmés. **Recalculer avec ces soudures** utilise
   le même masque et conserve les lignes manuelles et les revues enregistrées.
3. Dans **Suivi**, cliquer le départ puis l'arrivée. Les directions proposées
   contraignent la première sortie. Un échec ne force jamais une connexion.
   Conserver un chemin seulement après examen.
4. Dans **Ligne manuelle**, les clics successifs créent une chaîne avec jonctions
   aimantées. Maj contraint à 45°, Alt désactive l'aimant. **Terminer** arrête la
   chaîne. Dans **Tronçons**, Cmd/Ctrl-clic ajoute une sélection, le double-clic
   étend la chaîne jusqu'aux soudures ; supprimer retire la portion et ses
   superpositions exactes. Annuler/Rétablir restaure les données.
5. Molette pour zoomer, glisser le fond pour déplacer, **Carte entière** pour
   recadrer. Les surfaces larges sont violettes, les tracés manuels bleus. Les
   microcoupures photo, désactivées par défaut, sont orange si activées explicitement.
6. **Enregistrer** confirme la révision sur disque ; recharger vérifie la reprise.
   `workspace.previous.json` conserve la version précédente. Une autre fenêtre
   ayant enregistré provoque un conflit explicite ; ne pas ignorer ce message.

La revue compacte réutilise les moteurs de l'atelier, mais a son propre format
de workspace. Ne pas remplacer le JSON de l'ancien atelier par celui-ci. Le
prototype ne fournit pas encore de peinture/correction de masque ni de transfert
automatique vers l'ancien atelier : les lignes manuelles sont l'outil de secours.
Une sauvegarde explicite est nécessaire ; le changement de page avertit si des
corrections ne sont pas enregistrées. Les annulations restent limitées à la session.

## 5. Mesurer la répétabilité avant toute correction

Relancer la même commande vers `results/run-b`, puis :

```sh
./workshop compare results/run-a results/run-b --output results/repeatability.json
```

La comparaison recontrôle les fichiers utiles par SHA-256, y compris les masques,
points, routes, paramètres, provenance et workspace **initial**. Les temps, logs
et métadonnées de conteneur de l'export GIMP sont séparés ; les pixels canoniques
extraits restent comparés. La revue ultérieure modifie `workspace.json`, pas
`workspace.initial.json`. Le code et les versions d'exécution font partie de la
provenance : après un changement, créer un nouveau couple d'essais.

Une égalité prouve une répétabilité sur cette machine et ces versions. Elle ne
mesure ni la précision des soudures, ni l'isolation réelle des broches, ni la
justesse électrique. Pour celles-ci, constituer une annotation indépendante,
revoir la face composants et effectuer les vérifications physiques appropriées.

## Erreurs usuelles

| Message | Action |
|---|---|
| Dossier existant | Choisir un nouveau dossier, garder le précédent pour comparaison. |
| GIMP introuvable | Installer GIMP 3 ou fournir un PNG photographique opaque. |
| Extraction échouée | Lire `gimp.log`, vérifier le nom exact et l'unicité du calque. Pas de relance automatique. |
| Carte verte introuvable | Recadrer explicitement ou reconnaître que cette méthode ne convient pas à la photo. |
| Plus de 6 millions de pixels | Recadrer ou préparer une copie réduite et consigner cette préparation. |
| Entrée transparente | Fournir l'Original opaque, sans reprendre un détourage. |
| Résultat partiel | Examiner les limites et conserver l'échec ; ne pas l'annoncer comme reconstruction complète. |
| Port occupé | Choisir `--port 8877` ; ne pas arrêter un autre atelier. |
