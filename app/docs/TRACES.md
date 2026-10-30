# Détection pistes — 0.11.0

Le panneau Détection pistes regroupe le balayage automatique et la correction. Il reprend les panneaux voisins : repliable, bouton information pour la méthode et les gestes, roue crantée pour les paramètres. Préparation, Détection soudures et Calques gardent leur contenu. Le calque Pistes existant reçoit les tracés.

Détecter les pistes utilise le moteur CPU historique de fronts de Dijkstra : propagation pondérée dans le masque, rencontres entre ancrages voisins, conservation des boucles sans arbre couvrant. Il travaille sur l’alpha de la préparation actuelle et les soudures conservées, y compris les ajouts et déplacements manuels. Les points contenus dans une boîte plus grande restent des entrées ; les collisions d’ancrages sont signalées. Le filtre de section des soudures et les visibilités des calques ne limitent pas le calcul. Aucun appel à WeVisOne.

Sans préparation, le masque CPU initial est utilisé pour les anciens travaux. Un masque vide est refusé explicitement. L’alpha et la photo restent indépendants : les microcoupures s’appuient sur Original, pas sur le fond noir d’une image préparée. Le champ est reconstruit si la préparation ou l’option photo change, pas pour un simple déplacement de vue.

## Commandes

- Main déplace la carte. Sélectionner choisit un tronçon ; Cmd/Ctrl-clic ajoute ou retire, double-clic sélectionne sa chaîne jusqu’aux soudures. Supprimer enlève les tronçons. Valider / À revoir porte sur le chemin complet.
- Ligne ajoute des segments successifs avec jonctions virtuelles ; Terminer ou Échap finit la ligne. Maj contraint à 45°, Alt ignore l’aimantation.
- Suivre ouvre un nouveau départ/arrivée sur la carte. Les directions disponibles affinent la recherche ; Conserver intègre le chemin proposé. Reprendre dans la liste renseigne les deux extrémités et cherche un chemin, même sur une surface sans direction privilégiée.
- Revoir les chemins filtre les chemins à revoir, les microcoupures, surfaces larges, liens de rangées écartés et rejets. Cadrer montre le chemin complet ; Rétablir le marque accepté et rend visible une exception de rangée.
- Arrêter termine le Worker et conserve intégralement le résultat précédent. Une réponse à budget dépassé est explicitement partielle. Toute nouvelle application et ses corrections sont annulables.

Les réglages par défaut sont photo désactivée, protection des rangées active, 3 millions de pixels explorés et 10 secondes par passe. Les maxima restent 6 millions / 30 secondes, 2500 chemins automatiques et 250000 sommets, 2000 diagnostics ; supervision de l’opération complète à 90 secondes. Le champ reste limité à 6 millions de pixels. Les réglages sont sauvés sous traceSettings, indépendamment de la détection soudures.

La relance conserve les lignes, les fragments corrigés, les jonctions et les chemins acceptés/rejetés. Modifier les soudures ou la préparation rend les anciennes propositions automatiques périmées ; les tracés manuels restent consultables. Enregistrer conserve traceScan et traceSettings dans le workspace. Au chargement, aucun balayage n’est lancé.

## Validation et limites

41 tests Python et 15 tests Node passent. La validation navigateur est faite sur une copie du vrai workspace à 556 points : calcul, filtres, cadrage, revue, restauration d’une exception, suppression et annulation, suivi et conservation, ligne avec deux jonctions, arrêt sans perte, paramètres effectifs, budget partiel, relance et rechargement. Les champs de soudures et de préparation sont inchangés.

Sur cette préparation : 556 ancrages accrochés, 773 chemins stricts dont 450 traversant une surface large ; 40 liens de rangées masqués, soit 733 visibles, 47 diagnostics. 139227 visites de pixels le long des routes restent dans le masque préparé. Ces vérifications ne valident ni le détourage ni la connectivité électrique. La photo et ses hachures HT peuvent conserver de faux passages ; une surface large n’a pas d’axe unique. Les chiffres historiques sur Pistes V2 ne sont pas une référence de précision comparable.

Les calculs et corrections d’essai restent dans outputs/trace-panel-20261030-v1/qa-root. La sauvegarde de travail et sa copie Downloads n’ont pas été modifiées par l’intégration.
