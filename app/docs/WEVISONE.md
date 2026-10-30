# Prétraitements WeVisOne — atelier 0.10.3

## Interface

Toolbar : Ouvrir un travail JSON, Enregistrer, Exporter JSON, Annuler, Rétablir,
Ajuster à la carte. Les icônes possèdent un titre et un libellé accessible. Un
point sur Enregistrer signale une modification ; la réussite et l'heure sont
indiquées à côté. L'ouverture d'un JSON ne l'enregistre pas automatiquement et
reste annulable. Les imports d'une autre image sont refusés.

WeVisOne et Calques sont deux panneaux repliables ; le bouton information affiche
les détails techniques. Leur état replié est mémorisé dans ce navigateur.
Depuis 0.10.0, Préparation, Détection soudures et Calques restent séparés.
La réorganisation des outils de pistes reste un checkpoint distinct.

## Utilisation

1. Proposer le contour du PCB. Un clic = un appel modèle explicite.
2. Examiner l'aperçu rouge, puis cliquer **Appliquer**. Ce clic suffit ; aucune
   case de validation supplémentaire ni ouverture d'un nouveau travail.
3. Choisir une section du second passage, proposer le retrait de l'époxy, examiner
   son aperçu puis Appliquer. Répéter progressivement selon le besoin.
4. Enregistrer pour conserver l'état du crop. Annuler/Rétablir agit aussi sur ses
   changements. Recharger restitue le dernier état enregistré.

**Appliquer ne lance aucune détection de soudures ou de pistes.** Il compose
uniquement la transparence d'Original-croppé, dans le même travail. Les anciennes
propositions restent conservées, sont masquées après application et marquées
périmées ; elles ne sont pas automatiquement réinterprétées sur le nouveau crop.

Il y a un seul calque Original-croppé dans la liste. Original reste intact. Les
états précédents du crop sont des instantanés internes pour annulation et
traçabilité, pas de nouveaux calques ni de nouveaux travaux de détection.

Calques permet de choisir la visibilité d'Original, Original-croppé, Soudures et
Pistes. Les deux images sont superposables : Original visible derrière le crop
remplit ses zones transparentes. Pour examiner les exclusions sur damier,
afficher seulement Original-croppé. L'ancien masque cyan n'est plus un calque.
Le réglage des rangées reste dans les outils existants, hors de la liste des calques.

## Persistance

Le workspace conserve `preprocessing` (référence de l'instantané courant),
`layerVisibility` et ses corrections habituelles. Chaque instantané contient
`original-cropped.png`, `keep.png`, `board.png`, sa provenance, ses empreintes et
le lien vers son parent. Les artefacts résident dans `preprocessing/<id>/`.
Sauvegarder conserve la révision avec contrôle de concurrence et la copie
précédente. L'ouverture d'un JSON nécessite ses instantanés dans le dossier du
travail : Exporter JSON n'est pas une archive portable de toutes les images.

Le résultat modèle brut reste dans `model-jobs/<id>/`. Appliquer contrôle les
empreintes de la photo, du masque et du crop parent. Aucun résultat de détection
initial ni image source n'est écrasé. L'ancien endpoint public de création avec
détection automatique est désactivé ; les anciens résultats dérivés restent lisibles.

## Modèle et masques

Profil initial : WeVisOne-VL-2B, révision
`3dad9ce8bcb6fbe0aea945bf8860bd2cfc3663bf`, Transformers/MPS BF16, sans repli CPU
ni téléchargement. Le décodage des masques est activé pour les deux passages.

- Contour : `printed circuit board`, carte entière.
- Époxy : `green insulating board surface`, section choisie ou carte entière.
- Sections : 4 colonnes × 6 lignes, marge de contexte 64 pixels, seul le cœur
  est replacé dans le repère global. Un clic ne lance pas un lot de 24 requêtes.
- Époxy retiré seulement si masque modèle >=128 ET canal Lab a* bilatéral
  inférieur au seuil Otsu. Filtre bilatéral 7/15/5 ; Original n'est pas lissé.
- Contour et matière restent distincts ; le retrait d’époxy remplace la section
  choisie, en préservant les autres sections. Un réglage plus prudent peut donc
  restaurer des pixels ; Annuler reste disponible.

Pas de garantie de qualité des pistes fines, d'identité de matériau ou de
connectivité électrique. Les seuils et le prompt ne sont pas modifiés par cette
intervention d'interface.

## Exécution

Python et runtime WeVisOne découverts dans le moteur local configuré sur le NVMe.
Les gardes existants sont inchangés : un seul calcul, verrous partagés, mémoire
libre >=30 % avant lancement ; arrêt RSS >12 Gio, mémoire <15 %, swap +2 Gio,
durée >300 s. Contrôleur borné à 330 s. Aucun processus tiers arrêté. Aucune
inférence au chargement, aucune relance automatique après erreur.

Pour activer les changements, enregistrer les modifications dans l'ancienne
page, arrêter son serveur (Ctrl-C), puis relancer la même commande `workshop serve`
et recharger. Exemple depuis le dossier de l'app :

```
./workshop serve "../../outputs/mon-atelier-pcb-01" --port 8878
```

## Validation de l’interface initiale (0.5.0)

22 tests Python, dont la composition sans sous-processus, les seuils existants,
le remplacement par section, les empreintes et le décodage. Le navigateur a vérifié la toolbar,
les panneaux et le parcours complet sur une copie avec modèle simulé. Trois
itérations ont corrigé l'affichage des détections anciennes et la réapplication
d'un masque déjà utilisé, puis le retour d'enregistrement. Aucun modèle réel n'a été lancé pendant cette intervention.

## Ouvrir une image (0.6.0)

La toolbar Ouvrir accepte désormais PNG, XCF et JSON. Un PNG ouvre un nouveau
travail vide ; un XCF affiche la liste des calques et ouvre celui choisi. Le
calque Original est proposé par défaut s'il existe. Les groupes ne sont pas
sélectionnables ; deux calques homonymes restent distincts grâce à leur position
native. Annuler la boîte conserve la page courante.

Les modifications non enregistrées du travail courant sont enregistrées avant
l'import d'une autre image ; une erreur d'enregistrement bloque le changement.
Le nouveau travail est conservé dans `imports/<id>/workspace`, accessible sur
le même serveur avec `?result=<id>`. Son image et sa provenance sont conservées,
les soudures et pistes commencent à zéro. Ni détection ni inférence automatique.
L'ouverture d'un JSON garde le parcours précédent de restauration du travail.

Le XCF source est copié et lu dans un processus GIMP 3 distinct, sans sauvegarder
le XCF ni interagir avec la fenêtre GIMP déjà ouverte. Le rendu garde le canevas,
les offsets et la transparence du calque sélectionné. Aucune mise en miroir ni
rotation supplémentaire. Taille maximale : 256 Mio par fichier et 20 millions
de pixels pour l'image ouverte. GIMP 3 doit être présent pour les XCF.

## Réglages des propositions (0.7.0)

La roue crantée à droite de chaque action ouvre ses réglages propres. Les valeurs
initiales reprennent l'appel utilisé jusqu'ici. Utiliser valide les valeurs et
les mémorise dans le travail, sans modèle ni détection. Enregistrer dans la
barre d'outils les conserve sur disque, et donc après rechargement. Annuler
abandonne le formulaire ; Valeurs initiales ne devient effectif qu'après Utiliser.
Les modifications sont aussi couvertes par Annuler/Rétablir de la toolbar.

Réglages principaux : description recherchée et seuil du masque (1–254).
Pour le retrait d'époxy : seuil couleur Lab a*, vide pour Otsu automatique.
Un seuil Lab plus bas réduit la zone verte exclue. Augmenter le seuil du masque
conserve moins de contour PCB, mais retire moins d'époxy, selon l'action.
Ces réglages ne garantissent pas la préservation des pistes fines.

Les paramètres avancés exposent pixels vision, jetons, température, Top P,
Top K et pénalité de répétition. L'époxy expose aussi diamètre bilatéral
(impair), lissage couleur et lissage spatial. Les limites de vision 524288
pixels et 512 jetons restent les plafonds de cette intégration ; les gardes
mémoire et le backend ne sont pas modifiables dans cette fenêtre. Le choix du
modèle est disponible depuis la version 0.8.0.

Le prochain clic Proposer prend un instantané validé des paramètres dans
request.json ; le contrôleur les revalide et la provenance conserve les valeurs
utilisées. Changer les réglages ne modifie pas un masque déjà calculé. Un serveur
antérieur sans gestion de ces paramètres demande un redémarrage avant un appel.


## Remplacer une section (0.7.1)

Les réglages sont bien figés dans chaque calcul ; un réglage plus prudent était
cependant limité par l'ancien cumul des exclusions. L'aperçu puis Appliquer
remplacent maintenant le cœur de la section choisie par la nouvelle proposition,
y compris les pixels qu'elle conserve à nouveau. Les autres sections et le contour
PCB restent inchangés. Pour Carte entière, tout le retrait d'époxy est remplacé.
L'application reste explicite avec Appliquer et ne lance aucune détection.

Une proposition valide qui ne retire plus aucun pixel permet d'effacer le retrait
antérieur de sa section. Les anciens masques restent conservés pour Annuler.
Les propositions époxy des versions précédentes sont reconstruites en CPU depuis
leur masque brut et leurs paramètres enregistrés, avec contrôle des empreintes :
aperçu et application donnent le même remplacement, sans nouvelle inférence et
sans réécrire les anciens artefacts de calcul. Modifier les paramètres seuls
ne recalcule toujours pas une proposition déjà produite.


## Taille du modèle (0.8.0)

Chaque roue crantée affiche **Taille du modèle : 2B / 4B**, séparément pour
Contour du PCB et Retrait de l'époxy. Les travaux existants et les valeurs
initiales gardent 2B. Choisir 4B, cliquer Utiliser, puis Proposer pour lancer
explicitement ce modèle ; Enregistrer conserve le choix sur disque.

Les profils restent Transformers/MPS BF16, sans repli automatique. Un modèle
absent ou incomplet est grisé et un lancement forcé est refusé. La provenance
consigne la taille, l'identifiant et la révision réellement sélectionnés.
Le 4B officiel est épinglé à `6b44a45873b4bbc7dca383922504430dc60eca23`,
sous `WeVisOne-VL/models/WeVisOne-VL-4B` sur le NVMe. Ses poids BF16 sont natifs :
aucune conversion ni quantification. Le téléchargement vérifie tailles et SHA-256
LFS officiels avant d'écrire le reçu `download.json` et d'activer ce choix.
Les gardes de ressources et les plafonds de calcul restent identiques au 2B.

Validation de cette intégration : 24 tests Python, syntaxe JavaScript et Python.
Les tests du contrôleur vérifient la transmission du choix 4B avec moteur simulé ;
ils ne mesurent ni la qualité ni la consommation d'une inférence 4B réelle.


## Détection soudures (0.9.0)

Le panneau Détection soudures se replie indépendamment. Il propose Original-croppé
lorsqu'un crop est appliqué, sinon Original. Le choix concerne l'analyse ; la
visibilité des calques reste indépendante. Le bouton Détecter les soudures lance
uniquement un calcul CPU à la résolution d'origine (maximum 6 Mpx).

La méthode est celle de la version 0.2 : contraste gris par rapport à un flou
21×21, saturation <150, restriction Lab a* par Otsu, fermeture des reflets,
composantes et filtres de forme. Le contraste est toujours calculé sur Original,
jamais sur une image dont le fond aurait été noirci. Original-croppé fournit
seulement les domaines de carte et de pixels conservés.

La roue crantée expose restriction Lab, contraste et aires ; les paramètres
avancés ajoutent rondeur, dimension, allongement, fermeture et limite de candidats.
Les valeurs initiales reprennent le profil précédent : contraste 13, aire
100–2200 px², rondeur 0,05, dimension 85 px, allongement 3, fermeture 5 px,
limite 1500. Utiliser prépare la prochaine détection ; Enregistrer conserve.

Une détection remplace les propositions automatiques. Les points déplacés ou
rejetés sont conservés avec leurs corrections ; les ajouts manuels restent séparés.
Les nouvelles propositions proches de ces corrections sont évitées. Les identifiants
internes dépendent de la source et des boîtes, pour éviter de transférer une
correction à une soudure différente lorsque l'ordre des composantes change.
Sélectionner permet de choisir et déplacer un point ; Cmd/Ctrl-clic ajoute à la
sélection. Ajouter active le clic sur la carte ; Supprimer retire la sélection.
Les ajouts manuels sont bleus. Annuler/Rétablir couvre détection, réglages et éditions.

Les résultats et paramètres sont enregistrés dans solderDetection/solderSettings
du workspace ; candidates.json initial reste intact. Les anciennes pistes sont
conservées mais marquées à recalculer. Aucun calcul de pistes ou modèle n'est lancé.
Le worker des outils existants reçoit les points courants lors d'un calcul explicite.
La réorganisation du panneau pistes reste un checkpoint séparé.

Validation sur la photo de travail : 670 candidats sur Original, géométrie et
propriétés exactement identiques à la référence 0.2, répétition identique.
Sur les deux crops de contrôle (contour, puis époxy section), 662 candidats.
Ces nombres décrivent des propositions, sans vérité exhaustive des soudures.


## Détection WeVisOne et séparation des panneaux (0.10.0)

Le panneau des masques s'appelle **Préparation**. Il conserve Contour du PCB et
Époxy ; Appliquer modifie uniquement Original-croppé. Il se replie par défaut
lorsqu'un crop existe, en respectant la préférence d'ouverture déjà mémorisée.
**Détection soudures** utilise désormais WeVisOne ; les réglages CPU de 0.9.0
restent conservés dans les anciens travaux, sans être réutilisés par cette action.
**Calques** garde les quatre visibilités indépendantes.

Choisir l'image et la zone, puis Détecter les soudures. Carte entière lance au
maximum 24 requêtes séquentielles : grille 4×6, marge 64 px, fusion prudente entre
sections selon l'algorithme historique. Une seule section peut être relancée : son
cœur remplace les propositions automatiques de cette zone, les autres zones et
les corrections humaines sont conservées. Aucun calcul de pistes n'est lancé.

La roue crantée propose 2B/4B et la description recherchée. Les paramètres avancés
exposent pixels vision (plafond 524288), sortie (plafond 2048 jetons par section),
température, Top P/K et répétition. Le profil initial reprend la détection 2B
historique : individual silver-gray solder joints at component terminals,
2048 jetons, température 0. Les masques conservent leur plafond de 512 jetons.
Ces paramètres sont enregistrés séparément dans solderModelSettings.

L'entrée est figée : Original ou Original limité par l'alpha du crop choisi,
composé sur noir. Les calques affichés, les points et les corrections dessinées
ne sont pas des entrées du modèle. Chaque section garde sa réponse, l'audit EOS,
les limites, les empreintes et les ressources observées. Une réponse incomplète
arrête le lot ; aucune relance automatique, aucun repli CPU ou changement de modèle.
Les verrous globaux de préparation, détection et GUI sont conservés. Un seul
processus modèle à la fois ; gardes par requête inchangés (300 s, RSS 12 Gio,
mémoire disponible 15 %, swap +2 Gio), continuation du lot à ≥35 % disponible et
limite du lot 1200 s, avec supervision externe et délai de nettoyage.

Pendant le calcul, Arrêter est accessible et les actions concurrentes sont
bloquées. Enregistrer et Exporter restent disponibles pour le travail courant.
Un arrêt conserve les artefacts partiels mais n'applique pas leurs points.
Une réussite affiche les résultats dans la session qui a lancé le calcul. Après
rechargement, Afficher les résultats permet de les reprendre explicitement ;
une autre image ou préparation est refusée. Les résultats sont remplaçables,
annulables et enregistrables comme en 0.9.0. Aucun nouveau calcul au chargement.

Validation réelle du 29 octobre : 24 réponses complètes, 851 propositions brutes,
606 candidats après 245 rapprochements de doublons, environ 546 s. Toutes les
images des sections correspondent aux pixels figés. Aucun arrêt de garde ni
augmentation du swap mesurée ; RSS enfant maximum échantillonné 2,00 Gio,
mémoire système disponible minimum 36 %. Ces compteurs n'incluent pas toute la
mémoire GPU et ne doivent pas être additionnés aux compteurs du driver MPS.
Sur les 598 anciens centres conservés : 541 appariements à 16 px, contre 405
pour le CPU sur la même préparation. Sur les 32 témoins provisoires : 29 centres
couverts contre 27 pour le CPU ; l'ancien lot historique en couvrait 30.
Ces accords géométriques ne constituent pas une vérité exhaustive des soudures.

## Essais de soudures par section (0.10.1)

Une nouvelle détection remplace les propositions automatiques non corrigées dans
le cœur de la section. Les corrections manuelles et les autres sections restent
conservées. Les propositions de la marge de contexte sont ignorées, sans cumul.
Un résultat sans limites de section valides est refusé.

Choisir une section active **Afficher seulement cette section** : seuls ses
points sont dessinés et sélectionnables, dans un cadre pointillé. Décocher permet
de revoir toute la carte. Ce filtre ne supprime aucun point et ne limite pas
les données du calcul de pistes. Les compteurs distinguent les points de la
section, ceux conservés ailleurs et les observations brutes non encore appliquées.

La description des soudures accepte désormais une ligne de **1000 caractères**
(contre 200 auparavant), dans le formulaire comme sur le serveur. Les limites
des descriptions Contour/Époxy restent à 200. Un redémarrage du serveur est requis
pour activer cette nouvelle limite ; aucun modèle n'est chargé au redémarrage.

## Propositions superposées et identifiants (0.10.2)

Le modèle peut renvoyer plusieurs boîtes exactement identiques. Chacune conserve
ses coordonnées et reçoit désormais un identifiant distinct et déterministe :
le premier identifiant reste compatible avec les travaux existants, les suivants
portent un suffixe. Aucun chevauchement n'est supprimé par cette attribution.
La validation conserve ses contrôles et distingue une erreur de coordonnées d'un
identifiant répété. Ce contrôle technique ne valide pas la justesse des soudures.

## Modèle conservé en mémoire (0.10.3)

Le premier calcul explicite charge le modèle. Les opérations Contour, Époxy et
Soudures suivantes réutilisent les mêmes poids, y compris entre les sections
d'un lot. Modifier le prompt, les paramètres de génération ou les pixels vision
ne recharge pas les poids. Chaque requête garde une image, des jetons et des
artefacts distincts ; les sorties précédentes ne deviennent pas du contexte.

Le changement 2B/4B termine d'abord l'ancien processus, puis crée la session du
modèle demandé. **Décharger**, au-dessus des panneaux, libère la mémoire ; il
interrompt aussi un calcul actif. **Arrêter** un calcul libère également le
modèle. La fermeture du serveur, une erreur d'exécution ou une garde mémoire
terminent la session, sans relance automatique. Aucun chargement au démarrage.

Les verrous existants restent détenus pendant la résidence, même entre deux
opérations, pour empêcher un second chargement depuis l'autre interface locale.
Décharger permet de rendre le moteur à cette interface. Les plafonds par requête
et par lot restent inchangés. Une supervision reste active au repos : mémoire
disponible <15 %, swap +2 Gio depuis l'ouverture de la session ou RSS >12 Gio
provoquent la libération. La disparition du serveur termine aussi son worker.

Les métriques par requête exposent worker_pid, model_reused et model_load_seconds.
La réutilisation est vérifiée avec des processus et un moteur simulés ; les gains
de temps et le comportement MPS prolongé restent à mesurer sur un essai réel.
