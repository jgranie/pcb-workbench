# Méthode, dépendances et validation

Version 0.2 : la détection des soudures est désormais précédée d'une restriction
de matière Lab automatique, indépendante des anciens masques et BB. Le contraste
est calculé sur Original ; les pixels ne sont pas remplacés par du noir. Otsu
de a* propose le domaine hors époxy, puis les composantes brillantes y sont
restreintes avant fermeture. La rondeur minimale par défaut passe à 0,05.
Le tableau et les chiffres historiques plus bas décrivent les essais 0.1 ;
consulter `GUIDED_RUN.md` pour le nouveau parcours.

## Traitement effectué

| Étape | Automatisation | Hypothèse ou intervention résiduelle |
|---|---|---|
| Extraction XCF par nom | Automatique, copie et instance GIMP distinctes | Choisir le bon nom ; le nom ne garantit pas la provenance brute. |
| Orientation/cadrage | EXIF automatique, autres transformations explicites | Un contrôle initial de repère reste nécessaire ; aucune homographie automatique. |
| Enveloppe de carte | Automatique, vert HSV et plus grand contour | Carte verte ; des parties noires internes peuvent être incluses à tort. |
| Masque candidat | Otsu gris, seuil local ou Otsu de a* Lab | Inscriptions, reflets et corps de composants restent ambigus. |
| Soudures | Contraste local clair, composantes et filtres de forme | Les reflets fragmentent les soudures ; chiffres et trous produisent des faux candidats. |
| Ancrage et routes | Moteur JS CPU déterministe, masque 4-connexe | Une liaison dans un masque faux reste fausse ; un point est accroché à moins de 8 px. |
| Rangées de broches | Hypothèse géométrique, suppression réversible | Pas de preuve d'isolation ; aucune rangée incertaine imposée par coordonnées. |
| Corrections | Déplacement/rejet/ajout de points, suivi, lignes et jonctions | Revue humaine substantielle sur l'essai réel. Le masque n'a pas d'éditeur de peinture. |
| Millimètres / netlist | Non effectué | Calibration et validation électrique indépendantes restent à faire. |

L'enveloppe recherche saturation HSV >55, G >1,15R et G >0,90B. Une fermeture
9×9 aide le contour, puis son intérieur est rempli : cette **enveloppe n'est pas
le masque conducteur**. Le contraste des candidats soudures compare le gris à
un flou gaussien 21×21 et exige une saturation <150. Les paramètres de contraste,
aire, encombrement, circularité, rapport de forme et fermeture des reflets sont
dans `config.json`. Une fermeture 5×5 peut elle-même réunir des reflets voisins.
Le masque conducteur est le seuil choisi uni aux composantes brillantes retenues,
limité à l'enveloppe ; ses composantes de moins de 16 px sont retirées. Il ne
réutilise ni l'alpha de l'ancien travail, ni ses boîtes, ni des points annotés.

Les filtres sont exprimés en pixels pour la gamme de taille étudiée. Ils ne sont
pas invariants à l'échelle ou à la couleur de la carte. L'entrée limite la taille
à 6 Mpx et OpenCV utilise un thread, OpenCL désactivé. Une troncature à 1 500
candidats est marquée partielle, avec le nombre de candidats avant limite.

Le routage réutilise quatre modules géométriques du prototype initial, copiés
dans `web/core/`. Il accroche les centres des BB au masque, retire les BB incluses,
puis fait se rencontrer des fronts de Dijkstra pondérés par la distance aux bords.
Il n'énumère pas tous les cycles possibles entre une même paire de bornes.
Les limites de largeur (surface large >14 px), couronnes (14–80 px), et les pas
de rangées (20–95 px, au moins six positions) restent des heuristiques du moteur.
Les microcoupures photo sont désactivées par défaut ; leur option réutilise un
appui de contraste local et ne garantit pas la matière conductrice. Le raccord
sous reflet connu dans le travail initial n'est pas réparé par une exception.

## Ce qui a été vérifié

L'essai réel compare trois méthodes sans ancien masque ni anciennes boîtes en
entrée. La méthode grise reste le profil conservateur par défaut ; les variantes
sont sauvegardées séparément, sans sélectionner automatiquement celle qui
ressemble le plus au travail manuel. Un accord de masque ou de centres avec cet
ancien travail est une **mesure de désaccord**, pas une précision électrique.
Une inspection visuelle constate notamment des faux passages dans des zones
noires et des chiffres retenus comme soudures.

La répétabilité porte sur deux processus, deux extractions XCF et deux dossiers
neufs, avec les mêmes versions et le même code. Elle n'est pas certifiée entre
machines, versions de GIMP ou architectures. Un cas synthétique fournit une
vérité analytique très limitée ; aucune campagne de généralisation n'est acquise.

## Références techniques

- [Options GIMP](https://www.gimp.org/man/gimp.html) : nouvelle instance, traitement batch et sortie explicite.
- [Seuillage OpenCV](https://opencv.org/image-thresholding-using-opencv/) : seuil global, adaptatif et Otsu.

Ces documents expliquent les mécanismes utilisés ; ils ne valident pas ce
pipeline particulier pour la rétro-ingénierie électrique.
