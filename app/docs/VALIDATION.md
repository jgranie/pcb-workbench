# Validation locale du 28 octobre 2026

**Historique de la version 0.1.** Ces mesures de deux extractions XCF ne valent
pas qualification complète de la version 0.2. La copie 0.2 a passé les trois
tests Python, et son parcours PNG complet produit exactement les 670 BB de
la variante Lab/rondeur 0,05 mesurée séparément, puis 495 routes strictes. Les
nouveaux résultats de qualification sont dans le dossier d'audit local
`outputs/guided-workshop-20261028-v2/`, hors paquet distribuable.

## Résultat

Le parcours CPU depuis le calque Original a été exécuté dans des dossiers neufs,
sans importer le masque préparé ni les soudures du travail précédent. Deux
extractions XCF indépendantes, suivies de deux calculs, produisent des empreintes
identiques pour les **15 fichiers utiles** du résultat. Les durées et logs sont
séparés. L'entrée PNG issue du même Original produit aussi les mêmes pixels,
masques, candidats, routes et workspace initial ; sa provenance de conteneur
diffère volontairement de celle du XCF.

Le XCF contient un calque unique nommé Original, indice natif 3, 1984×2782,
décalage nul, opacité 100 %, mode normal, sans masque de calque. Son rendu RGBA
est identique à l'export Original de l'atelier précédent. Aucun miroir ni
recadrage supplémentaire n'a été appliqué. Le nom et le contenu du XCF ne
permettent pas de reconstituer les transformations antérieures à son enregistrement.

Versions : Python 3.12.2, Node 26.8.2, GIMP 3.2.4, versions Python du verrou.
Durées observées : 16,8 et 17,4 secondes pour les deux parcours XCF complets ;
2,6 secondes pour le parcours PNG. Ce sont des mesures locales, pas une promesse
de performance sur d'autres machines. Aucun calcul de modèle ni poids chargé.

## Exactitude encore insuffisante

| Méthode | IoU avec l'ancien masque manuel | Routes strictes | Routes de surface large | Diagnostics |
|---|---:|---:|---:|---:|
| Otsu gris, défaut | 72,8 % | 274 | 119 | 338 |
| Seuil local | 57,4 % | 284 | 37 | 361 |
| Otsu a* Lab | 70,7 % | 433 | 306 | 148 |

Les trois méthodes utilisent les mêmes **455 candidats classiques**, sans
troncature ; 454 restent après exclusion des BB incluses. Le seuil gris retrouve
81,8 % des pixels opaques de l'ancien masque mais ajoute 304 953 pixels en dehors
de celui-ci et en omet 449 946. Les zones noires, trous, chiffres et reflets restent
problématiques. Le nombre plus élevé de routes Lab ne prouve pas une amélioration.

Un appariement un-à-un à distance maximale de 16 px retrouve **225 correspondances**
avec les 598 points non rejetés de l'ancien travail. Il reste 373 points de
référence sans correspondant et 230 candidats nouveaux non appariés. Ces écarts
ne sont **pas** des faux négatifs/faux positifs certifiés : la référence provient
d'un VLM et de corrections manuelles, sans vérité indépendante. Le détecteur peut
fragmenter une même soudure ou prendre un trou/une inscription pour une borne.
Une seule rangée est proposée sur ces ancrages, contre quatre sur les anciens.

Les 338 diagnostics du profil gris comprennent 186 directions sans liaison
couverte et 152 ancrages isolés. Toutes les visites de pixels le long des routes
strictes ont été contrôlées dans le **nouveau masque**, ce qui ne prouve pas que
ce masque correspond au cuivre réel. La calibration physique et l'électricité
restent non validées. Le raccord sous reflet historique reste hors réussite.

## Tests et revue

Cinq tests passent : trois Python et deux JavaScript. L'exemple synthétique
retrouve six bornes et cinq liaisons, conserve l'anneau à quatre côtés et sépare
deux réseaux. Les tests refusent notamment l'écrasement d'un résultat, un alpha
préparé et un résultat modifié avant sa revue. Ils vérifient aussi la conservation
des sources et les jonctions manuelles.

Une copie de test distincte a servi à la revue dans un navigateur réel : dessin
d'une chaîne, sauvegarde/rechargement, sélection en chaîne, suppression,
Annuler/Rétablir, suivi entre deux nouveaux candidats, ajout/déplacement d'une
pastille, invalidation puis recalcul et nouvelle sauvegarde/reprise. Les gestes
Cmd de sélection multiple sont implémentés ; leur scénario complet n'a pas fait
l'objet d'une qualification séparée dans cette version compacte. Les captures
privées sont conservées dans le dossier d'audit local, exclu de l'archive.

Une entrée XCF demandant un nom de calque inexistant échoue explicitement et
conserve son journal. L'ancien atelier, ses PNG, ses deux XCF, ses réglages et ses
corrections ne sont pas des destinations d'écriture du paquet.

## Limite de livraison

Ce résultat est un prototype reproductible accompagné d'une revue. Il ne satisfait
pas encore l'objectif pratique d'une reconstruction fiable avec peu de corrections.
La prochaine amélioration devrait porter d'abord sur l'identité des soudures,
avec un petit lot de validation indépendant, avant d'ajouter des règles de
routage. Une autre prise de vue moins floue et moins réfléchissante pourrait
aussi changer la qualité d'entrée ; cet effet n'a pas été mesuré ici.

La publication reste une décision ultérieure : licence du code et droits des
images à confirmer. L'archive n'inclut que l'exemple synthétique.
