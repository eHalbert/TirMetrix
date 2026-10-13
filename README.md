<img src="docs/capture-principale.png" alt="Fenêtre principale de TirMetrix" width="800">

# TirMetrix

**Analyse de cible ISSF C50 pour le tir à 25 m.**

TirMetrix est une application de bureau (Python / Tkinter) qui permet d'analyser la photo d'un carton de tir : redressement de la perspective, calibrage automatique ou manuel des bagues, marquage des impacts à la souris, puis calcul du score et de statistiques de groupement (CEP, cercle minimal, ellipse de dispersion, flyers, historique…).

> ⚠️ TirMetrix est un outil d'entraînement personnel. Ses résultats n'ont **aucune valeur officielle** : le score et les mesures dépendent de la qualité de la photo, de la calibration et du placement manuel des impacts.

<!-- Ajouter ici une ou deux captures d'écran :
![Fenêtre principale](docs/capture-principale.png)
-->

## Fonctionnalités

**Préparation de la cible**
- Détection automatique du carton et correction de perspective à l'ouverture d'une photo.
- « Calibrer le carton » : correction manuelle en 4 clics sur les coins, avec choix des dimensions du carton (formats courants proposés, ou dimensions personnalisées).
- « Calibrer la zone 1 » : calibrage par au moins 3 clics sur le bord de la zone 1 (clic droit ou Entrée pour valider). Le centre et l'échelle X/Y sont déduits de l'ajustement, avec un curseur de précision de type CAO.
- Détection automatique du centre (point rouge) et de l'échelle (bagues 1 et 2, ou disque noir en secours).

**Marquage et score**
- Modes Ajouter / Supprimer / Déplacer pour les impacts, annulation, zoom à la molette.
- Score selon la règle ISSF (le bord le plus proche du trou compte), avec choix du calibre : 9 mm Parabellum ou .22 LR.

**Statistiques**
- Score total, moyenne, meilleur/pire tir, écart-type, répartition par bague.
- Dispersion, diamètre maximal, cercle minimal englobant (MEC), décalage moyen.
- CEP 50 / CEP 90 par rapport au groupement (dispersion) et par rapport au point visé (centrage).
- Ellipse de dispersion (axe majeur/mineur, rapport d'aspect, orientation) et coefficient de variation.
- Fiabilité selon le nombre de tirs : intervalle de confiance de la moyenne, détection des flyers, taux de flyers (intervalle de Wilson), risque d'au moins un flyer.
- Info-bulles explicatives sur chaque statistique.

**Sessions et suivi**
- « Exporter tout » : CSV des impacts, JSON de la session, image annotée et image rectifiée.
- « Reprendre cible » : rechargement d'une session depuis son JSON.
- « Historique » : évolution des statistiques sur l'ensemble des cartons exportés dans un dossier (double-clic pour rouvrir un carton).
- « Stabilité balle » : calculateur de stabilité gyroscopique (formule de Miller) avec pas de Greenhill indicatif.

## Installation

Prérequis : **Python 3.10 ou plus récent** (Tkinter est inclus avec l'installeur Python officiel ; sous Linux, installer le paquet `python3-tk`).

```bash
git clone https://github.com/<votre-compte>/TirMetrix.git
cd TirMetrix
pip install -r requirements.txt
```

## Utilisation

```bash
python TirMetrix.py                 # puis « Nouvelle cible »
python TirMetrix.py ma_cible.jpg    # ouvre directement une photo
```

Déroulement conseillé :

1. **Nouvelle cible** : ouvrir la photo (JPG, PNG, BMP, TIFF).
2. Si la perspective n'a pas été détectée ou semble fausse, utiliser **Calibrer le carton**, choisir les dimensions du carton, puis cliquer les 4 coins (haut-gauche, haut-droit, bas-droit, bas-gauche).
3. Vérifier que les cercles violets se superposent aux bagues imprimées. Sinon, utiliser **Calibrer la zone 1**.
4. Choisir le **calibre**, puis cliquer sur chaque impact en mode **Ajouter**.
5. Lire les statistiques dans les panneaux latéraux, puis **Exporter tout** pour sauvegarder la session.

Astuces : la molette zoome sur le curseur ; **Centrer le carton** remet la vue d'ensemble sans toucher à la calibration.

## Créer un exécutable Windows

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name TirMetrix --icon target.ico --add-data "target_32.png;." TirMetrix.py
```

L'exécutable est généré dans `dist/`. Le script `build_windows.bat` fourni fait cette opération. Sous Linux/macOS, remplacer `;` par `:` dans `--add-data`.

## Dépendances

- [OpenCV](https://opencv.org/) (`opencv-python`)
- [NumPy](https://numpy.org/)
- [Pillow](https://python-pillow.org/)
- Tkinter (bibliothèque standard)

## Limites connues

- L'interface est actuellement uniquement en français.
- Les formats de carton proposés varient selon les fabricants : vérifiez les dimensions de votre carton ou saisissez-les.
- La détection automatique suppose un carton clair sur un fond différent et à peu près carré.
- Les indicateurs statistiques (intervalles de confiance, flyers) sont indicatifs, surtout sur de petites séries.

## Contribuer

Les retours, signalements de bugs (avec une photo de cible si possible) et suggestions sont les bienvenus via les *issues* du dépôt.

## Licence

Copyright (c) 2026 Édouard HALBERT — CC BY-NC 4.0.
