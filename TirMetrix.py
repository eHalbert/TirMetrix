"""
Target Analyzer — ISSF C50 25m Pistol
Manual impact marking with mouse, auto-calibrated ring geometry.

Usage:
    python tirmetrix.py [image_path]

Dependencies:
    pip install opencv-python numpy Pillow
    
License
    Copyright (c) 2026 Édouard HALBERT — CC BY-NC 4.0
"""

import sys
import os
import math
import json
import glob
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import cv2
import numpy as np
from PIL import Image, ImageTk, ImageDraw, ImageFont


def resource_path(relative_path: str) -> str:
    """Resolve the path to a bundled resource (e.g. the app icon), whether
    running as a plain script or as a PyInstaller-frozen executable (where
    bundled files are unpacked to the sys._MEIPASS temp folder)."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class ToolTip:
    """Small hover tooltip attached to a single Tkinter widget.

    Shows a short explanatory popup below the mouse cursor after the mouse
    has stayed over the widget for `delay_ms`, and hides it as soon as the
    mouse leaves or a click happens. Used to explain statistic names on
    hover. Positioned well below the cursor (not under the widget) so the
    cursor never ends up hovering over the tooltip text itself.
    """

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._tip_win: tk.Toplevel | None = None
        self._pointer_xy = (0, 0)
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Motion>", self._track, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _track(self, event):
        self._pointer_xy = (event.x_root, event.y_root)

    def _schedule(self, event=None):
        self._cancel_pending()
        if event is not None:
            self._pointer_xy = (event.x_root, event.y_root)
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel_pending(self):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        if self._tip_win is not None or not self.text:
            return
        px, py = self._pointer_xy
        x = px + 14
        y = py + 24  # well below the cursor so it never sits under the text
        self._tip_win = tk.Toplevel(self.widget)
        self._tip_win.wm_overrideredirect(True)
        try:
            self._tip_win.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self._tip_win.wm_geometry(f"+{x}+{y}")
        # Thin white border frame around the tooltip for extra contrast.
        border = tk.Frame(self._tip_win, bg="#ffffff")
        border.pack()
        tk.Label(
            border,
            text=self.text,
            justify="left",
            bg="#000000",
            fg="#ffee00",
            font=("Consolas", 9, "bold"),
            wraplength=260,
            padx=7,
            pady=5,
        ).pack(padx=1, pady=1)

    def _hide(self, _event=None):
        self._cancel_pending()
        if self._tip_win is not None:
            self._tip_win.destroy()
            self._tip_win = None


# ---------------------------------------------------------------------------
# Explanatory text shown as a tooltip when the mouse hovers a statistic's
# name in the side panels. Keyed by the exact label/section text used in
# the UI so it's easy to keep in sync when a label changes.
# ---------------------------------------------------------------------------
STAT_HELP: dict[str, str] = {
    # RÉSUMÉ
    "Score total": "Somme des points de tous les impacts marqués sur la cible.",
    "Moyenne / tir": "Score total divisé par le nombre de tirs (points par impact).",
    "Meilleur": "Le tir ayant obtenu le score le plus élevé.",
    "Plus mauvais": "Le tir ayant obtenu le score le plus faible.",
    "Écart-type": "Dispersion des scores autour de la moyenne : plus il est faible, plus les scores sont réguliers.",
    "% du score max": "Score total rapporté au score maximum théorique de la série (N tirs × 10 points).",
    # RÉPARTITION PAR BAGUE
    "RÉPARTITION PAR BAGUE": "Nombre d'impacts tombés dans chaque zone (bague) de la cible.",
    # FIABILITÉ (N tirs)
    "N tirs": "Nombre total d'impacts pris en compte dans les statistiques.",
    "Score éq. / 10 tirs": "Score moyen par tir extrapolé sur une série théorique de 10 tirs (moyenne × 10).",
    "IC moyenne à 95 %": "Intervalle de confiance à 95 % pour la vraie moyenne des scores, compte tenu du nombre de tirs.",
    "Flyers détectés": "Nombre d'impacts très éloignés du groupement (tirs aberrants), repérés en rouge sur le dessin.",
    "Taux de flyers": "Proportion de tirs identifiés comme flyers parmi tous les tirs.",
    "IC taux flyers": "Intervalle de confiance à 95 % (Wilson) sur le taux de flyers estimé.",
    "Risque d'≥1 flyer": "Probabilité d'avoir au moins un flyer sur une série de N tirs, étant donné le taux observé.",
    "Tirs moyens avant flyer": "Nombre moyen de tirs attendu entre deux flyers, à ce taux observé.",
    # CALIBRATION
    "CALIBRATION": "Échelle de conversion pixels ↔ millimètres utilisée pour toutes les mesures de distance.",
    # CURSEUR
    "CURSEUR": "Position du curseur sur l'image et sa distance au centre de la cible.",
    # AFFICHAGE toggles
    "Axe de dispersion (PCA)": "Affiche l'axe principal de dispersion du groupement (analyse en composantes principales) et son angle.",
    "Cercle CEP 50 (groupement)": "Affiche le cercle CEP 50, centré sur le groupement, contenant 50 % des impacts.",
    "Cercle CEP 90 (groupement)": "Affiche le cercle CEP 90, centré sur le groupement, contenant 90 % des impacts.",
    "Cercle MEC (groupement)": "Affiche le plus petit cercle contenant tous les impacts (MEC : Minimum Enclosing Circle).",
    # Right panel sections
    "DISPERSION": "Étalement des impacts autour du barycentre du groupement : rayon moyen, écart-type radial et écart-type par axe (X/Y).",
    "Rayon moyen": "Distance radiale moyenne des impacts au barycentre du groupement.",
    "Écart-type rayon": "Écart-type des distances au barycentre du groupement : régularité de la dispersion.",
    "Écart-type X": "Écart-type des écarts horizontaux (X) des impacts autour du barycentre du groupement.",
    "Écart-type Y": "Écart-type des écarts verticaux (Y) des impacts autour du barycentre du groupement.",
    "GROUPEMENT": "Taille du groupement d'impacts, indépendamment du point visé : diamètre max (extreme spread) et diamètre MEC.",
    "Diamètre max": "Distance maximale entre deux impacts quelconques du groupement (extreme spread).",
    "Diamètre MEC": "Diamètre du plus petit cercle contenant tous les impacts (Minimum Enclosing Circle).",
    "DÉCALAGE MOYEN": "Décalage moyen (biais) du groupement par rapport au point visé, en X et en Y.",
    "ΔX moyen": "Décalage horizontal moyen du groupement par rapport au point visé (positif = à droite).",
    "ΔY moyen": "Décalage vertical moyen du groupement par rapport au point visé (positif = vers le bas de l'image).",
    "CEP — GROUPEMENT (dispersion)": "Rayons CEP 50 / CEP 90 calculés par rapport au centre du groupement : mesurent la dispersion pure, indépendamment du réglage de visée.",
    "CEP 50 (groupement)": "Rayon du cercle, centré sur le groupement, contenant 50 % des impacts.",
    "CEP 90 (groupement)": "Rayon du cercle, centré sur le groupement, contenant 90 % des impacts.",
    "CEP — POINT VISÉ (centrage)": "Rayons CEP 50 / CEP 90 et rayon moyen calculés par rapport au point visé (centre de la cible) : mesurent la précision globale, dispersion + décalage.",
    "CEP 50 (point visé)": "Rayon du cercle, centré sur le point visé, contenant 50 % des impacts.",
    "CEP 90 (point visé)": "Rayon du cercle, centré sur le point visé, contenant 90 % des impacts.",
    "Rayon moyen (point visé)": "Distance radiale moyenne des impacts au point visé (centre de la cible).",
    "Écart-type rayon (point visé)": "Écart-type des distances au point visé : régularité de la précision globale (dispersion + décalage).",
    "ELLIPSE": "Paramètres de l'ellipse de dispersion (grand axe, petit axe, rapport d'aspect, orientation) ajustée sur le nuage d'impacts.",
    "Axe majeur": "Longueur du grand axe de l'ellipse de dispersion (2σ le long de la direction de plus grande variance).",
    "Axe mineur": "Longueur du petit axe de l'ellipse de dispersion (2σ le long de la direction de plus faible variance).",
    "Rapport d'aspect": "Rapport grand axe / petit axe de l'ellipse : proche de 1 = groupement plutôt circulaire, élevé = groupement allongé.",
    "Angle": "Orientation du grand axe de l'ellipse, en degrés depuis le nord (haut de la cible), sens horaire (est = 90°).",
    "CONSISTANCE": "Coefficient de variation du rayon de groupement (écart-type / moyenne) : plus il est faible, plus les tirs sont réguliers en dispersion.",
    "Coef. variation (rayon)": "Écart-type du rayon de groupement divisé par sa moyenne : indicateur sans dimension de la régularité du groupement.",
}


def _attach_tooltip(widget: tk.Widget, key: str):
    """Attach a ToolTip to `widget` using the explanation registered for
    `key` in STAT_HELP, if any. No-op (and no crash) when there is none."""
    text = STAT_HELP.get(key)
    if text:
        ToolTip(widget, text)


FLYER_SIGMA = 2.0  # outlier threshold used for flyer detection, mean + k*std (single source of truth)

# ---------------------------------------------------------------------------
# ISSF C50 ring geometry — outer radius of each scoring ring in mm
# 25m Pistol target: 10-ring r=25mm, each ring +25mm up to ring 7 (r=100mm),
# then +50mm per ring outward.
# ---------------------------------------------------------------------------
RINGS_MM: dict[int, float] = {
    10: 25.0,
    9: 50.0,
    8: 75.0,
    7: 100.0,
    6: 125.0,
    5: 150.0,
    4: 175.0,
    3: 200.0,
    2: 225.0,
    1: 250.0,
}

# Scoring ring overlay colors — violet/purple tones
RING_COLORS = {
    10: "#cc88ff",
    9: "#bb77ee",
    8: "#aa66dd",
    7: "#9955cc",
    6: "#8844bb",
    5: "#7733aa",
    4: "#993388",
    3: "#aa44aa",
    2: "#bb55bb",
    1: "#cc66cc",
}

# Caliber definitions: display name → bullet radius in mm
# Scoring rule: effective distance = centre_distance − bullet_radius
CALIBERS: dict[str, float] = {
    "9 mm Parabellum": 4.50,  # 9.00 mm diameter
    ".22 LR": 2.80,  # 5.60 mm diameter
}
CALIBER_DEFAULT = "9 mm Parabellum"

IMPACT_RADIUS_SCREEN = 8  # circle radius on screen (px)
IMPACT_COLOR = "#ff4444"
IMPACT_BORDER = "#ffffff"
IMPACT_SELECTED = "#ffff00"


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

TARGET_SIZE_PX = 1500  # resolution (px) of the longer side of the rectified image

# Physical dimensions of the printed target card. The ISSF C50 card stock
# used here is NOT perfectly square (522 mm wide x 534 mm tall) — if the
# perspective correction warped it to a square canvas anyway, the printed
# (truly circular) scoring rings would come out slightly elliptical in
# pixel space, no longer matching the app's circular ring/zone overlays.
# Adjust these two values if a different card stock is used.
CARD_WIDTH_MM = 522.0
CARD_HEIGHT_MM = 534.0

# Rectified canvas size, in pixels, matching the card's true (non-square)
# aspect ratio: the longer physical side maps to TARGET_SIZE_PX, and the
# other side is scaled down by the same mm/px factor. This keeps mm/px
# identical on both axes, so a physical circle stays a circle after warping.
def card_canvas_size_px(width_mm: float, height_mm: float) -> tuple[int, int]:
    """Return the (width_px, height_px) of the rectified canvas for a card
    of the given physical size. The longer side maps to TARGET_SIZE_PX and
    the shorter one is scaled by the same mm/px factor."""
    if height_mm >= width_mm:
        return round(TARGET_SIZE_PX * width_mm / height_mm), TARGET_SIZE_PX
    return TARGET_SIZE_PX, round(TARGET_SIZE_PX * height_mm / width_mm)


TARGET_WIDTH_PX, TARGET_HEIGHT_PX = card_canvas_size_px(CARD_WIDTH_MM, CARD_HEIGHT_MM)

# Card sizes offered in the "Calibrer le carton" dialog: (label, width_mm, height_mm).
# Sizes vary between manufacturers/shops, so check the one printed on your
# own target's packaging, or use the custom entry in the dialog.
CARD_PRESETS: list[tuple[str, float, float]] = [
    ("Carton mesuré (défaut) — 522 × 534 mm", 522.0, 534.0),
    ("Carré standard — 520 × 520 mm", 520.0, 520.0),
    ("Grand format — 550 × 550 mm", 550.0, 550.0),
]


class CardSizeDialog(tk.Toplevel):
    """Modal dialog to choose the physical size of the target card: a list
    of common sizes plus a custom width/height entry. After `wait_window`,
    `self.result` holds (width_mm, height_mm), or None if cancelled."""

    CUSTOM = "custom"

    def __init__(self, master: tk.Tk, initial: tuple[float, float]):
        super().__init__(master)
        self.title("Dimensions du carton")
        self.configure(bg="#0f0f14")
        self.resizable(False, False)
        self.transient(master)
        self.result: tuple[float, float] | None = None

        # Pre-select the preset matching the last used size, else "custom".
        selected = self.CUSTOM
        for i, (_label, w, h) in enumerate(CARD_PRESETS):
            if abs(w - initial[0]) < 0.01 and abs(h - initial[1]) < 0.01:
                selected = str(i)
        self._choice = tk.StringVar(value=selected)
        self._w_var = tk.StringVar(value=f"{initial[0]:g}")
        self._h_var = tk.StringVar(value=f"{initial[1]:g}")

        body = tk.Frame(self, bg="#12121c", padx=16, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text="DIMENSIONS DU CARTON", bg="#12121c", fg="#55ff55", font=("Consolas", 9, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 8))

        def radio(text, value):
            r = tk.Radiobutton(
                body,
                text=text,
                variable=self._choice,
                value=value,
                bg="#12121c",
                fg="#ffffff",
                selectcolor="#1e1e30",
                activebackground="#12121c",
                activeforeground="#ffffff",
                font=("Consolas", 9),
                anchor="w",
            )
            r.pack(fill=tk.X, pady=2)
            return r

        for i, (label, _w, _h) in enumerate(CARD_PRESETS):
            radio(label, str(i))

        radio("Dimensions personnalisées :", self.CUSTOM)

        custom = tk.Frame(body, bg="#12121c")
        custom.pack(fill=tk.X, padx=(24, 0), pady=(2, 0))

        def entry(var):
            e = tk.Entry(
                custom, textvariable=var, bg="#1e1e30", fg="#e0e0f0", insertbackground="#e0e0f0", relief=tk.FLAT, font=("Consolas", 9), justify="right", width=7
            )
            # Typing in a field implies the user wants the custom size.
            e.bind("<Key>", lambda _e: self._choice.set(self.CUSTOM))
            e.bind("<FocusIn>", lambda _e: self._choice.set(self.CUSTOM))
            return e

        tk.Label(custom, text="Largeur", bg="#12121c", fg="#b0b0d0", font=("Consolas", 9)).pack(side=tk.LEFT)
        entry(self._w_var).pack(side=tk.LEFT, padx=(4, 10))
        tk.Label(custom, text="Hauteur", bg="#12121c", fg="#b0b0d0", font=("Consolas", 9)).pack(side=tk.LEFT)
        entry(self._h_var).pack(side=tk.LEFT, padx=(4, 4))
        tk.Label(custom, text="mm", bg="#12121c", fg="#b0b0d0", font=("Consolas", 9)).pack(side=tk.LEFT)

        self._err_var = tk.StringVar(value="")
        tk.Label(body, textvariable=self._err_var, bg="#12121c", fg="#ff5555", font=("Consolas", 8), anchor="w", wraplength=380, justify="left").pack(
            fill=tk.X, pady=(8, 0)
        )

        btns = tk.Frame(self, bg="#0f0f14", padx=16, pady=10)
        btns.pack(fill=tk.X)
        tk.Button(
            btns, text="Annuler", command=self._cancel, bg="#555570", fg="#ffffff", relief=tk.FLAT, font=("Consolas", 9, "bold"), padx=12, pady=5, cursor="hand2"
        ).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(
            btns, text="Valider", command=self._ok, bg="#3a6fd8", fg="#ffffff", relief=tk.FLAT, font=("Consolas", 9, "bold"), padx=12, pady=5, cursor="hand2"
        ).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        # Centre over the parent window, then make the dialog modal.
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - h) // 2)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.focus_set()

    def _ok(self):
        choice = self._choice.get()
        if choice == self.CUSTOM:
            try:
                w = float(self._w_var.get().replace(",", "."))
                h = float(self._h_var.get().replace(",", "."))
            except ValueError:
                self._err_var.set("Valeurs invalides : saisissez des nombres (ex. 520).")
                return
            # 500 mm is the diameter of ring 1, so the card must be larger.
            if not (500.0 < w <= 2000.0 and 500.0 < h <= 2000.0):
                self._err_var.set("Dimensions hors plage : chaque côté doit être > 500 mm (diamètre de la zone 1) et ≤ 2000 mm.")
                return
            self.result = (w, h)
        else:
            _label, w, h = CARD_PRESETS[int(choice)]
            self.result = (w, h)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def _order_quad_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as [TL, TR, BR, BL] regardless of the order they
    were found in (works for both an approxPolyDP quad and minAreaRect box)."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(d)]
    bl = pts[np.argmax(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _quad_from_mask(mask: np.ndarray, W: int, H: int) -> np.ndarray | None:
    """Extract a plausible target-card quadrilateral from a binary mask
    (255 = candidate card pixels). Returns ordered corners or None if the
    mask doesn't yield a large, roughly square blob.

    A rotated minAreaRect is used (rather than a strict 4-point
    approxPolyDP) because it tolerates a jagged mask boundary — caused by
    shadows or a busy background eating into the blob — much better than
    a polygon fit does, at the cost of assuming the true shape is close
    to a rectangle (true here, since the card itself is square)."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea)
    area_frac = cv2.contourArea(cnt) / (W * H)
    if area_frac < 0.15:
        return None  # nothing large enough found
    if area_frac > 0.98:
        # Almost the entire frame: most likely the background wasn't
        # separated from the card at all (e.g. a uniform/noisy image with
        # no real card in it), rather than a genuinely tight photo — treat
        # as an unreliable detection instead of trusting it blindly.
        return None

    rect = cv2.minAreaRect(cnt)
    rw, rh = rect[1]
    if rw == 0 or rh == 0:
        return None
    # The card is square: reject a fit whose sides differ by more than 20 %,
    # since that means the mask leaked into the background (or missed part
    # of the card) and the corners can't be trusted.
    if max(rw, rh) / max(1.0, min(rw, rh)) > 1.20:
        return None

    return _order_quad_corners(cv2.boxPoints(rect))


def detect_target_corners(img_bgr: np.ndarray) -> np.ndarray | None:
    """
    Detect the four corners of the target card against its background.
    Returns a (4, 2) float32 array ordered [TL, TR, BR, BL], or None if
    no confident detection could be made — the caller should then leave
    the raw photo untouched and let the user run the manual "Calibrer le
    carton" instead of silently applying a wrong warp.

    Two strategies are tried, in order:
      1. HSV-based: the card is a light, low-saturation sheet of paper,
         while most backgrounds (wood, cloth, floors) are either more
         saturated in colour or simply darker. We score each pixel by
         "brightness minus saturation" and split it with Otsu's method,
         which adapts to this photo's own lighting instead of relying on
         one hand-picked brightness value.
      2. Grayscale fallback: the legacy fixed-brightness thresholds, kept
         for lighting conditions where the HSV approach doesn't separate
         card from background well (e.g. a very pale/white background).
    Both strategies are validated with the same plausibility checks
    (large enough, square enough) before being accepted.
    """
    H, W = img_bgr.shape[:2]

    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    _, s_ch, v_ch = cv2.split(hsv)
    paper_score = cv2.GaussianBlur(cv2.subtract(v_ch, s_ch), (9, 9), 0)
    _, mask = cv2.threshold(paper_score, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    corners = _quad_from_mask(mask, W, H)
    if corners is None:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        for thresh_val in [160, 140, 120, 100]:
            _, mask = cv2.threshold(blurred, thresh_val, 255, cv2.THRESH_BINARY)
            corners = _quad_from_mask(mask, W, H)
            if corners is not None:
                break

    if corners is None:
        return None

    # Shrink the quad slightly inward (toward its centre) to reliably trim
    # the last sliver of background that a coarse mask boundary tends to
    # leave along the edges, without cutting into the printed target itself.
    centroid = corners.mean(axis=0)
    return centroid + (corners - centroid) * 0.985


def correct_perspective(img_bgr: np.ndarray, corners: np.ndarray, width: int = TARGET_WIDTH_PX, height: int = TARGET_HEIGHT_PX) -> np.ndarray:
    """
    Apply a perspective transform to rectify the target card.
    corners: (4, 2) float32 array [TL, TR, BR, BL].
    Returns the rectified image of shape (height, width, 3).

    The output canvas is NOT forced to be square: its width/height ratio
    matches the card's true CARD_WIDTH_MM x CARD_HEIGHT_MM proportions, so
    the mm/px scale is identical on both axes and printed (truly circular)
    scoring rings stay circular in pixel space after the warp.
    """
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(img_bgr, M, (width, height))


def detect_target_center(img_bgr: np.ndarray) -> tuple[float, float] | None:
    """Detect the red aiming dot at the centre of the C50 target."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, np.array([0, 150, 150]), np.array([10, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([165, 150, 150]), np.array([180, 255, 255]))
    mask = cv2.bitwise_or(red1, red2)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = max((c for c in cnts if cv2.contourArea(c) > 200), key=cv2.contourArea, default=None)
    if best is None:
        return None
    M = cv2.moments(best)
    return (M["m10"] / M["m00"], M["m01"] / M["m00"]) if M["m00"] else None


def detect_rings_1_and_2(img_bgr: np.ndarray) -> tuple[float, float, float] | None:
    """
    Calibrate using the two outermost C50 scoring rings (ring 1 = 250 mm, ring 2 = 225 mm).
    These rings are on the plain beige paper, unaffected by any reactive target
    stuck over the black disc area.

    Method: compute the mean gradient magnitude on concentric annuli centred on the
    image centre, then find the pair of peaks whose radius ratio is closest to
    250/225 = 1.1111.  The mm/px estimate is averaged from both rings.

    Returns (cx_px, cy_px, mm_per_px) or None.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    W, H = img_bgr.shape[1], img_bgr.shape[0]
    img_cx = W / 2.0
    img_cy = H / 2.0

    # Gradient magnitude
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.sqrt(gx**2 + gy**2)

    # Distance from image centre for every pixel
    ys, xs = np.mgrid[0:H, 0:W]
    r_map = np.sqrt((xs - img_cx) ** 2 + (ys - img_cy) ** 2)

    # Radial scan range covering rings 1 and 2 (35–62 % of the shorter side)
    r_lo = int(min(W, H) * 0.35)
    r_hi = int(min(W, H) * 0.62)
    r_bins = np.arange(r_lo, r_hi + 1)

    # Mean gradient strength on each thin annulus
    strengths = np.array([float(np.mean(mag[np.abs(r_map - r) < 2.5])) for r in r_bins])

    # Simple local-maximum finder (no scipy required)
    def local_peaks(signal: np.ndarray, min_dist: int = 10, min_height: float | None = None) -> np.ndarray:
        height_thresh = min_height if min_height is not None else np.percentile(signal, 60)
        peaks = []
        for i in range(1, len(signal) - 1):
            if signal[i] > height_thresh and signal[i] >= signal[i - 1] and signal[i] > signal[i + 1]:
                if not peaks or (i - peaks[-1]) >= min_dist:
                    peaks.append(i)
                elif signal[i] > signal[peaks[-1]]:
                    peaks[-1] = i  # replace with stronger neighbour
        return np.array(peaks, dtype=int)

    peaks = local_peaks(strengths, min_dist=10, min_height=np.percentile(strengths, 60))
    if len(peaks) < 2:
        return None

    peak_radii = r_bins[peaks]

    # Find the pair with ratio closest to 250/225 within ±6 %
    TARGET_RATIO = 250.0 / 225.0
    RATIO_TOL = 0.06
    best_err = float("inf")
    best = None

    for i, ra in enumerate(peak_radii):
        for rb in peak_radii[i + 1 :]:
            r_big, r_sml = (ra, rb) if ra > rb else (rb, ra)
            err = abs(r_big / r_sml - TARGET_RATIO)
            if err < RATIO_TOL and err < best_err:
                best_err = err
                best = (r_big, r_sml)

    if best is None:
        return None

    r1_px, r2_px = best
    mpp = (250.0 / r1_px + 225.0 / r2_px) / 2.0
    return float(img_cx), float(img_cy), float(mpp)


def detect_black_disc(img_bgr: np.ndarray) -> tuple[float, float, float] | None:
    """
    Fallback: detect the outer boundary of the black disc (ring 6/7 boundary = 125 mm).
    Used only when the ring-1/ring-2 detection fails.
    Returns (cx, cy, radius_px).
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (15, 15), 0)
    _, dark = cv2.threshold(blurred, 80, 255, cv2.THRESH_BINARY_INV)
    cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    largest = max(cnts, key=cv2.contourArea)
    (cx, cy), r = cv2.minEnclosingCircle(largest)
    return float(cx), float(cy), float(r)


def minimum_enclosing_circle(pts: np.ndarray) -> tuple[float, float, float]:
    """
    Minimum enclosing circle using OpenCV's exact algorithm (Welzl / Boundarys).
    pts: (N, 2) array in any unit (float).  Returns (cx, cy, radius).
    cv2.minEnclosingCircle expects float32 and shape (N, 1, 2).
    """
    if len(pts) == 0:
        return 0.0, 0.0, 0.0
    if len(pts) == 1:
        return float(pts[0, 0]), float(pts[0, 1]), 0.0
    pts32 = pts.astype(np.float32).reshape(-1, 1, 2)
    (cx, cy), r = cv2.minEnclosingCircle(pts32)
    return float(cx), float(cy), float(r)


def score_impact(dx_mm: float, dy_mm: float) -> int:
    """Return the ISSF score for an impact at (dx_mm, dy_mm) from centre."""
    dist = math.hypot(dx_mm, dy_mm)
    for score in sorted(RINGS_MM, reverse=True):
        if dist <= RINGS_MM[score]:
            return score
    return 0


def cep_from_distances(dists_mm: np.ndarray, percentile: float) -> float:
    """
    Generic CEP (Circular Error Probable) helper: the radius containing
    `percentile` % of impacts around whatever centre `dists_mm` was measured
    from. The caller decides the reference centre by choosing what goes into
    `dists_mm`:
      - distances to the GROUP BARYCENTRE  -> "CEP groupement" (internal
        dispersion / precision, independent of any aiming bias),
      - distances to the POINT OF AIM (target centre) -> "CEP point visé"
        (dispersion AS EXPERIENCED at the point of aim, i.e. it also bakes
        in any systematic bias/decentring).
    Both are legitimate "CEP50" values; they just answer different
    questions, so they must never be silently mixed.
    """
    if len(dists_mm) == 0:
        return 0.0
    return float(np.percentile(dists_mm, percentile))


# Student's t two-sided 95% critical values (t_{0.975, df}), df = n - 1.
# Used instead of a fixed z=1.96 because shot-group sample sizes are small
# and the normal approximation understates the interval at low n.
# Beyond df=30 the difference from 1.96 is negligible, so z is used instead
# of extending the table.
_T95_TABLE = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.160,
    14: 2.145,
    15: 2.131,
    16: 2.120,
    17: 2.110,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.080,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.060,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def t_critical_95(df: int) -> float:
    """Two-sided 95% Student's t critical value for `df` degrees of freedom."""
    if df <= 0:
        return float("nan")
    if df > 30:
        return 1.96
    return _T95_TABLE[df]


def wilson_score_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """
    Wilson score 95% confidence interval for a binomial proportion k/n.
    Preferred over the naive normal approximation for small n and/or
    proportions near 0 or 1 (e.g. "1 flyer out of 20 shots"), where the
    naive interval can go negative or exceed 1.
    """
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    return max(0.0, lo), min(1.0, hi)


def detect_flyers(centered_mm: np.ndarray, sigma_k: float = FLYER_SIGMA) -> np.ndarray:
    """
    Flag "flyer" impacts: shots whose radial distance from the GROUP
    BARYCENTRE exceeds mean + sigma_k * std (simple two-sigma outlier rule
    on the group's own dispersion). Needs >= 2 shots to define a std.
    Returns a boolean mask, same length/order as `centered_mm`.
    """
    n = len(centered_mm)
    if n < 2:
        return np.zeros(n, dtype=bool)
    mean_r = float(np.mean(centered_mm))
    std_r = float(np.std(centered_mm))
    if std_r == 0.0:
        return np.zeros(n, dtype=bool)
    threshold = mean_r + sigma_k * std_r
    return centered_mm > threshold


def compute_reliability_stats(scores: list[int], centered_mm: np.ndarray, flyer_sigma: float = FLYER_SIGMA) -> dict:
    """
    Compute the N-dependent reliability/consistency indicators for the
    current string of shots:
      - score_eq10:              total score rescaled to a 10-shot string,
      - mean_ci95:                95% CI on the true mean score (Student's t),
      - n_flyers / flyer_rate:    outlier shots (see `detect_flyers`),
      - flyer_rate_ci95:          Wilson 95% CI on the flyer rate,
      - flyer_risk_n:             P(>=1 flyer) in a string of `n` shots,
                                   assuming shots are i.i.d. Bernoulli(p),
      - mean_shots_before_flyer:  expected number of shots between flyers
                                   (1/p of a geometric distribution).
    The last three treat the OBSERVED flyer rate as an estimate of the
    shooter's long-run rate — they describe risk going forward, not just
    what happened in this string.
    """
    n = len(scores)
    result = {
        "n": n,
        "score_eq10": None,
        "mean_ci95": None,
        "n_flyers": 0,
        "flyer_rate": None,
        "flyer_rate_ci95": None,
        "flyer_risk_n": None,
        "mean_shots_before_flyer": None,
    }
    if n == 0:
        return result

    avg = sum(scores) / n
    result["score_eq10"] = avg * 10

    if n >= 2:
        std_s = float(np.std(scores, ddof=1))  # sample std (unbiased)
        t = t_critical_95(n - 1)
        margin = t * std_s / math.sqrt(n)
        result["mean_ci95"] = (avg - margin, avg + margin)

    mask = detect_flyers(centered_mm, flyer_sigma)
    n_flyers = int(np.sum(mask))
    p = n_flyers / n
    result["n_flyers"] = n_flyers
    result["flyer_rate"] = p
    result["flyer_rate_ci95"] = wilson_score_interval(n_flyers, n)
    result["flyer_risk_n"] = 1.0 - (1.0 - p) ** n
    result["mean_shots_before_flyer"] = (1.0 / p) if p > 0 else None
    return result


# ---------------------------------------------------------------------------
# Multi-target history / evolution
# ---------------------------------------------------------------------------

# Metrics that can be plotted across targets: label -> (json key, unit,
# "higher is better" flag used only to colour the trend indicator; None
# means the metric has no obvious "better" direction (e.g. a signed bias).
HISTORY_METRICS: dict[str, tuple[str, str, bool | None]] = {
    "Moyenne / tir": ("average", "pts", True),
    "Score total": ("total_score", "pts", True),
    "Écart-type score": ("std_score", "pts", False),
    "CEP 50 (groupement)": ("cep50_group_mm", "mm", False),
    "CEP 90 (groupement)": ("cep90_group_mm", "mm", False),
    "CEP 50 (point visé)": ("cep50_poi_mm", "mm", False),
    "CEP 90 (point visé)": ("cep90_poi_mm", "mm", False),
    "Rayon moyen": ("mean_radius_mm", "mm", False),
    "Écart-type rayon": ("std_radius_mm", "mm", False),
    "Diamètre MEC": ("mec_diameter_mm", "mm", False),
    "Biais ΔX": ("bias_dx_mm", "mm", None),
    "Biais ΔY": ("bias_dy_mm", "mm", None),
}


def scan_export_folder(folder: str) -> tuple[list[dict], int]:
    """
    Recursively scan `folder` for '*_data.json' session files produced by
    '_write_json' / 'Exporter tout', and return a chronologically sorted
    list of flattened session summaries plus a count of unreadable files.

    Each summary dict merges the useful bits of 'metadata' and 'statistics'
    so the History window doesn't need to know about the JSON's nesting.
    """
    paths = sorted(glob.glob(os.path.join(folder, "**", "*_data.json"), recursive=True))
    sessions: list[dict] = []
    n_errors = 0

    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("metadata", {})
            stats = data.get("statistics", {})

            summary = {
                "path": path,
                "file": os.path.basename(path),
                "image": meta.get("image", os.path.basename(path)),
                "date": meta.get("date", ""),
                "time": meta.get("time", ""),
                "n_impacts": meta.get("n_impacts", 0),
            }
            for _, (key, _unit, _) in HISTORY_METRICS.items():
                summary[key] = stats.get(key)
            sessions.append(summary)
        except (OSError, json.JSONDecodeError, AttributeError):
            n_errors += 1

    # Chronological order: ISO date/time strings sort correctly as text.
    # Sessions with no date (older/incomplete exports) are pushed to the end.
    sessions.sort(key=lambda s: (s["date"] == "", s["date"], s["time"]))
    return sessions, n_errors


# Miller's velocity correction is floored at the speed of sound (1120 ft/s).
MILLER_MIN_VELOCITY_FPS = 1120.0

# Below this length (in calibers) the Miller correlation is an extrapolation:
# the worked examples of the original paper span roughly 3.4 to 5 calibers.
MILLER_SHORT_BULLET_CALIBERS = 3.0


def greenhill_twist_in(diameter_mm: float, length_mm: float, density_g_cm3: float = 10.9, c: float = 150.0) -> float:
    """Greenhill's rule of thumb: twist (in/turn) = C * D^2 / L * sqrt(rho / 10.9).

    D and L are in inches. C = 150 is meant for velocities up to ~2800 ft/s
    (180 above). It gives a 'safe' twist (SG ~ 1.5-2 at 2800 ft/s, according
    to Miller), NOT a stability factor, and it only depends on the bullet
    length: it is a reference value, not a substitute for Miller's SG.
    """
    if min(diameter_mm, length_mm, density_g_cm3, c) <= 0:
        raise ValueError("All physical values must be strictly positive.")
    d_in = diameter_mm / 25.4
    l_in = length_mm / 25.4
    return c * d_in ** 2 / l_in * (density_g_cm3 / 10.9) ** 0.5


def sg_miller(
    mass_grains: float,
    diameter_mm: float,
    length_mm: float,
    twist_in_per_turn: float,
    velocity_m_s: float,
    temperature_c: float = 15.0,
    pressure_hpa: float = 1013.25,
) -> float:
    """Gyroscopic stability factor (SG) using Miller's formula, with
    velocity and air-density corrections.

    Intended mainly for bullets with a fairly homogeneous core density
    (classic lead core + jacket). Raises ValueError on non-physical input.
    """
    if min(mass_grains, diameter_mm, length_mm, twist_in_per_turn, velocity_m_s, pressure_hpa) <= 0:
        raise ValueError("All physical values must be strictly positive.")

    mm_per_inch = 25.4
    ms_to_fps = 3.280839895

    d = diameter_mm / mm_per_inch          # diameter in inches
    length_in = length_mm / mm_per_inch
    l = length_in / d                      # length in calibers
    t = twist_in_per_turn / d              # twist in calibers per turn
    velocity_fps = velocity_m_s * ms_to_fps

    # Base Miller formula
    sg_base = 30.0 * mass_grains / (t ** 2 * d ** 3 * l * (1.0 + l ** 2))

    # Velocity correction: Miller's reference velocity is 2800 ft/s.
    # Miller (2005) explicitly floors it at the speed of sound (1120 ft/s):
    # below Mach 1 the overturning-moment correlation is no longer valid, so
    # the Mach 1 value is reused. This matters for pistol and subsonic
    # rimfire loads, where the uncapped cube root under-estimates SG by ~10 %.
    velocity_correction = (max(velocity_fps, MILLER_MIN_VELOCITY_FPS) / 2800.0) ** (1.0 / 3.0)

    # Air density correction: SG increases as air gets less dense
    temperature_k = temperature_c + 273.15
    standard_temperature_k = 288.15
    standard_pressure_hpa = 1013.25
    air_correction = (standard_pressure_hpa / pressure_hpa) * (temperature_k / standard_temperature_k)

    return sg_base * velocity_correction * air_correction


def sg_regime(sg: float) -> tuple[str, str]:
    """Return a (label, color) pair giving a qualitative reading of SG."""
    if sg < 1.00:
        return "Instable : risque de basculement ou de trous ovales.", "#ff5555"
    if sg < 1.20:
        return "Marginal : peut fonctionner, mais marge faible.", "#ffaa33"
    if sg < 1.40:
        return "Acceptable : stabilité généralement suffisante.", "#ffee55"
    if sg <= 2.00:
        return "Bonne marge de stabilité.", "#55ff55"
    return "Stabilité gyroscopique très élevée.", "#55ffaa"


def bullet_rpm(velocity_m_s: float, twist_in_per_turn: float) -> float:
    """Approximate projectile spin rate in rpm."""
    velocity_mm_s = velocity_m_s * 1000.0
    twist_mm_per_turn = twist_in_per_turn * 25.4
    turns_per_second = velocity_mm_s / twist_mm_per_turn
    return turns_per_second * 60.0


class StabilityWindow(tk.Toplevel):
    """
    Gyroscopic stability (SG, Miller formula) calculator: input fields for
    the bullet/barrel/environment parameters on top, computed SG and its
    interpretation at the bottom.
    """

    # Sensible defaults so the window opens pre-filled (e.g. 9x19mm 124gr FMJ)
    _DEFAULTS = {
        "mass_grains": "124.0",
        "diameter_mm": "8.9",
        "length_mm": "15.0",
        "twist_in": "9.7",
        "velocity_m_s": "360.0",
        "temperature_c": "15.0",
        "pressure_hpa": "1013.25",
    }

    def __init__(self, master: "TargetApp"):
        super().__init__(master)
        self.title("Stabilité gyroscopique de la balle (Miller)")
        self.configure(bg="#0f0f14")
        self.resizable(False, False)
        self._center_on_parent(master, width=420, height=560)

        self._entries: dict[str, tk.Entry] = {}
        self._build_ui()
        self._calculate()  # show a result immediately, using the defaults

    def _center_on_parent(self, master: tk.Tk, width: int, height: int):
        master.update_idletasks()
        px, py = master.winfo_rootx(), master.winfo_rooty()
        pw, ph = master.winfo_width(), master.winfo_height()
        x = px + max(0, (pw - width) // 2)
        y = py + max(0, (ph - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # -- UI ------------------------------------------------------------

    def _build_ui(self):
        # ---- Top part: input fields -----------------------------------
        top = tk.Frame(self, bg="#12121c", padx=14, pady=12)
        top.pack(fill=tk.X)

        tk.Label(
            top, text="PARAMÈTRES", bg="#12121c", fg="#55ff55", font=("Consolas", 9, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 8))

        fields = [
            ("mass_grains", "Masse (grains)"),
            ("diameter_mm", "Diamètre (mm)"),
            ("length_mm", "Longueur de balle seule (mm)"),
            ("twist_in", "Pas de rayure (pouces/tour)"),
            ("velocity_m_s", "Vitesse (m/s)"),
            ("temperature_c", "Température (°C)"),
            ("pressure_hpa", "Pression (hPa)"),
        ]
        for key, label in fields:
            row = tk.Frame(top, bg="#12121c")
            row.pack(fill=tk.X, pady=3)
            entry = tk.Entry(
                row,
                bg="#1e1e30",
                fg="#e0e0f0",
                insertbackground="#e0e0f0",
                relief=tk.FLAT,
                font=("Consolas", 9),
                justify="right",
                width=8,
            )
            entry.insert(0, self._DEFAULTS[key])
            # Pack the entry first so it reserves its (small, fixed) space,
            # then let the label claim all the remaining row width instead
            # of a hardcoded character width, which used to clip long
            # labels like "Longueur de balle seule (mm)".
            entry.pack(side=tk.RIGHT)
            tk.Label(row, text=label, bg="#12121c", fg="#ffffff", font=("Consolas", 9), anchor="w").pack(
                side=tk.LEFT, fill=tk.X, expand=True
            )
            entry.bind("<Return>", lambda _e: self._calculate())
            self._entries[key] = entry

        tk.Button(
            top,
            text="Calculer",
            command=self._calculate,
            bg="#3a6fd8",
            fg="#ffffff",
            relief=tk.FLAT,
            font=("Consolas", 9, "bold"),
            padx=10,
            pady=6,
            cursor="hand2",
            activebackground="#50508a",
            activeforeground="#ffffff",
        ).pack(fill=tk.X, pady=(10, 0))

        tk.Frame(self, bg="#222235", height=1).pack(fill=tk.X)

        # ---- Bottom part: result and explanation -----------------------
        bottom = tk.Frame(self, bg="#0f0f14", padx=14, pady=14)
        bottom.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            bottom, text="RÉSULTAT", bg="#0f0f14", fg="#55ff55", font=("Consolas", 9, "bold"), anchor="w"
        ).pack(fill=tk.X, pady=(0, 6))

        self._sg_var = tk.StringVar(value="—")
        tk.Label(bottom, textvariable=self._sg_var, bg="#0f0f14", fg="#ffffff", font=("Consolas", 34, "bold")).pack()

        self._regime_var = tk.StringVar(value="")
        self._regime_lbl = tk.Label(
            bottom,
            textvariable=self._regime_var,
            bg="#0f0f14",
            fg="#ffffff",
            font=("Consolas", 9, "bold"),
            wraplength=380,
            justify="center",
        )
        self._regime_lbl.pack(pady=(2, 10))

        tk.Frame(bottom, bg="#222235", height=1).pack(fill=tk.X, pady=(0, 10))

        self._detail_var = tk.StringVar(value="")
        tk.Label(
            bottom,
            textvariable=self._detail_var,
            bg="#0f0f14",
            fg="#b0b0d0",
            font=("Consolas", 8),
            justify="left",
            anchor="w",
            wraplength=380,
        ).pack(fill=tk.X)

        tk.Label(
            bottom,
            text=(
                "SG < 1.00 instable · 1.00–1.20 marginal · 1.20–1.40 acceptable\n"
                "1.40–2.00 bonne marge · > 2.00 forte stabilité\n\n"
                "Utiliser la longueur de la balle seule (pas la cartouche entière).\n"
                "Le coefficient balistique (BC) n'intervient pas dans ce calcul.\n"
                "Sous Mach 1 (~341 m/s), la correction de vitesse est figée à sa valeur Mach 1."
            ),
            bg="#0f0f14",
            fg="#666680",
            font=("Consolas", 8),
            justify="left",
            anchor="w",
            wraplength=380,
        ).pack(fill=tk.X, pady=(12, 0))

    # -- Logic -----------------------------------------------------------

    def _calculate(self):
        try:
            mass_grains = float(self._entries["mass_grains"].get().replace(",", "."))
            diameter_mm = float(self._entries["diameter_mm"].get().replace(",", "."))
            length_mm = float(self._entries["length_mm"].get().replace(",", "."))
            twist_in = float(self._entries["twist_in"].get().replace(",", "."))
            velocity_m_s = float(self._entries["velocity_m_s"].get().replace(",", "."))
            temperature_c = float(self._entries["temperature_c"].get().replace(",", "."))
            pressure_hpa = float(self._entries["pressure_hpa"].get().replace(",", "."))

            sg = sg_miller(
                mass_grains=mass_grains,
                diameter_mm=diameter_mm,
                length_mm=length_mm,
                twist_in_per_turn=twist_in,
                velocity_m_s=velocity_m_s,
                temperature_c=temperature_c,
                pressure_hpa=pressure_hpa,
            )
            regime_label, regime_color = sg_regime(sg)
            rpm = bullet_rpm(velocity_m_s, twist_in)

            self._sg_var.set(f"SG = {sg:.2f}")
            self._regime_var.set(regime_label)
            self._regime_lbl.configure(fg=regime_color)
            # Reference twist (Greenhill) and short-bullet warning
            greenhill_in = greenhill_twist_in(diameter_mm, length_mm)
            length_cal = length_mm / diameter_mm
            lines = [
                f"Vitesse de rotation estimée : {rpm:,.0f} tr/min".replace(",", " "),
                f"Pas Greenhill de référence : {greenhill_in:.1f} in/tour (indicatif)",
            ]
            if length_cal < MILLER_SHORT_BULLET_CALIBERS:
                lines.append(
                    f"Balle courte ({length_cal:.1f} cal) : extrapolation de la corrélation de "
                    "Miller, ordre de grandeur seulement."
                )
            self._detail_var.set("\n".join(lines))
        except (ValueError, ZeroDivisionError) as exc:
            self._sg_var.set("—")
            self._regime_var.set(f"Entrée invalide : {exc}")
            self._regime_lbl.configure(fg="#ff5555")
            self._detail_var.set("")


class HistoryWindow(tk.Toplevel):
    """
    Displays the evolution of a shooter's statistics across every target
    ('carton') exported to a chosen folder: a session list on the left and
    a line chart of the selected metric on the right.
    """

    def __init__(self, master: "TargetApp", folder: str, sessions: list[dict]):
        super().__init__(master)
        self.title("Historique / Évolution des tirs")
        self.configure(bg="#0f0f14")
        self.minsize(800, 500)
        self._center_on_parent(master, width=1400, height=820)

        self._folder = folder
        self._sessions = sessions
        self._metric_var = tk.StringVar(value="Moyenne / tir")

        self._build_ui()
        self._draw_chart()

    def _center_on_parent(self, master: tk.Tk, width: int, height: int):
        """Size the window and centre it over the main application window
        rather than over the whole screen."""
        master.update_idletasks()
        px, py = master.winfo_rootx(), master.winfo_rooty()
        pw, ph = master.winfo_width(), master.winfo_height()
        x = px + max(0, (pw - width) // 2)
        y = py + max(0, (ph - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    # -- UI ------------------------------------------------------------

    def _build_ui(self):
        top = tk.Frame(self, bg="#1a1a24", pady=6, padx=10)
        top.pack(fill=tk.X)

        tk.Label(top, text=f"📁 {self._folder}", bg="#1a1a24", fg="#b0b0d0", font=("Consolas", 8)).pack(side=tk.LEFT)

        tk.Label(top, text=f"  |  {len(self._sessions)} carton(s)", bg="#1a1a24", fg="#55ff55", font=("Consolas", 8, "bold")).pack(side=tk.LEFT)

        right_top = tk.Frame(top, bg="#1a1a24")
        right_top.pack(side=tk.RIGHT)
        tk.Label(right_top, text="Indicateur : ", bg="#1a1a24", fg="#ffffff", font=("Consolas", 9)).pack(side=tk.LEFT)
        metric_cb = tk.OptionMenu(right_top, self._metric_var, *HISTORY_METRICS.keys(), command=lambda _: self._draw_chart())
        metric_cb.config(
            bg="#2a2a40",
            fg="#e0e0f0",
            relief=tk.FLAT,
            font=("Consolas", 9),
            activebackground="#50508a",
            activeforeground="#ffffff",
            highlightthickness=0,
            width=18,
        )
        metric_cb["menu"].config(bg="#2a2a40", fg="#e0e0f0", font=("Consolas", 9))
        metric_cb.pack(side=tk.LEFT, padx=(0, 4))

        self._show_avg_var = tk.BooleanVar(value=False)
        avg_cb = tk.Checkbutton(
            right_top,
            text="Moyenne/tir",
            variable=self._show_avg_var,
            command=self._draw_chart,
            bg="#1a1a24",
            fg="#cccccc",
            selectcolor="#2a2a40",
            activebackground="#1a1a24",
            activeforeground="#ffffff",
            font=("Consolas", 9),
        )
        avg_cb.pack(side=tk.LEFT, padx=(4, 8))

        tk.Button(
            right_top,
            text="↻ Actualiser",
            command=self._refresh,
            bg="#30304a",
            fg="#e0e0f0",
            relief=tk.FLAT,
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=3,
            cursor="hand2",
        ).pack(side=tk.LEFT)

        main = tk.Frame(self, bg="#0f0f14")
        main.pack(fill=tk.BOTH, expand=True)

        # -- Left: session list --
        left = tk.Frame(main, bg="#12121c", width=340)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 2), pady=4)
        left.pack_propagate(False)

        tk.Label(left, text="CARTONS (ordre chronologique)", bg="#12121c", fg="#55ff55", font=("Consolas", 8), anchor="w").pack(fill=tk.X, padx=8, pady=(6, 2))

        cols = ("n", "date", "avg", "total", "impacts")
        self._tree = ttk.Treeview(left, columns=cols, show="headings", height=20)
        for col, label, width in [("n", "#", 30), ("date", "Date", 90), ("avg", "Moy.", 55), ("total", "Total", 55), ("impacts", "Impacts", 55)]:
            self._tree.heading(col, text=label)
            self._tree.column(col, width=width, anchor="center")
        self._tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        for i, s in enumerate(self._sessions, 1):
            avg = s.get("average")
            total = s.get("total_score")
            self._tree.insert(
                "",
                "end",
                iid=str(i - 1),
                values=(
                    i,
                    s["date"] or "—",
                    f"{avg:.2f}" if avg is not None else "—",
                    total if total is not None else "—",
                    s.get("n_impacts", "—"),
                ),
            )
        self._tree.bind("<<TreeviewSelect>>", lambda e: self._draw_chart())
        self._tree.bind("<Double-1>", self._on_row_double_click)

        # -- Right: chart --
        right = tk.Frame(main, bg="#0f0f14")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=4, padx=(2, 4))

        self._canvas = tk.Canvas(right, bg="#0a0a10", highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Configure>", lambda e: self._draw_chart())

        self._trend_var = tk.StringVar(value="—")
        self._trend_lbl = tk.Label(right, textvariable=self._trend_var, bg="#0f0f14", fg="#ffffff", font=("Consolas", 9), anchor="w")
        self._trend_lbl.pack(fill=tk.X, pady=(4, 0))

    def _on_row_double_click(self, event):
        """Double-clicking a session row closes the History window and
        loads that carton straight into the main window, as if the user
        had used 'Reprendre cible' and picked that JSON file."""
        row_id = self._tree.identify_row(event.y)
        if not row_id:
            return  # double-click missed any row (e.g. header/empty area)

        session = self._sessions[int(row_id)]
        master = self.master
        self.destroy()
        master._load_session_from_json(session["path"])

    def _refresh(self):
        """Re-scan the same folder in case new exports were added."""
        sessions, n_errors = scan_export_folder(self._folder)
        self._sessions = sessions
        for item in self._tree.get_children():
            self._tree.delete(item)
        for i, s in enumerate(self._sessions, 1):
            avg = s.get("average")
            total = s.get("total_score")
            self._tree.insert(
                "",
                "end",
                iid=str(i - 1),
                values=(
                    i,
                    s["date"] or "—",
                    f"{avg:.2f}" if avg is not None else "—",
                    total if total is not None else "—",
                    s.get("n_impacts", "—"),
                ),
            )
        self._draw_chart()

    # -- Chart -----------------------------------------------------------

    def _draw_chart(self):
        """Draw a simple line chart of the selected metric across sessions."""
        c = self._canvas
        c.delete("all")

        metric_label = self._metric_var.get()
        key, unit, higher_is_better = HISTORY_METRICS[metric_label]

        # Collect (index, value) pairs for sessions that actually have this metric.
        points = [(i, s[key]) for i, s in enumerate(self._sessions) if s.get(key) is not None]
        if len(points) < 1:
            c.create_text(20, 20, anchor="nw", fill="#ffaa44", font=("Consolas", 10), text="Aucune donnée disponible pour cet indicateur.")
            self._trend_var.set("—")
            return

        w = max(c.winfo_width(), 200)
        h = max(c.winfo_height(), 200)
        margin_l, margin_r, margin_t, margin_b = 60, 30, 30, 50

        xs_idx = [p[0] for p in points]
        ys_val = [p[1] for p in points]
        y_min, y_max = min(ys_val), max(ys_val)
        if y_min == y_max:
            y_min -= 1.0
            y_max += 1.0
        pad = (y_max - y_min) * 0.12
        y_min -= pad
        y_max += pad

        n_slots = max(len(self._sessions) - 1, 1)

        def x_of(i):
            return margin_l + (w - margin_l - margin_r) * (i / n_slots if n_slots else 0.5)

        # For metrics where a lower value is better (dispersion, CEP, MEC, ...),
        # flip the mapping so the "good" direction still points up on screen,
        # matching the score metrics (higher_is_better=True) above/below logic.
        invert_axis = higher_is_better is False

        def y_of(v):
            frac = (v - y_min) / (y_max - y_min)
            if invert_axis:
                return margin_t + (h - margin_t - margin_b) * frac
            return margin_t + (h - margin_t - margin_b) * (1 - frac)

        # -- Grid + y-axis labels --
        n_grid = 5
        for g in range(n_grid + 1):
            gv = y_min + (y_max - y_min) * g / n_grid
            gy = y_of(gv)
            c.create_line(margin_l, gy, w - margin_r, gy, fill="#222235")
            c.create_text(margin_l - 8, gy, anchor="e", fill="#888899", font=("Consolas", 8), text=f"{gv:.1f}")

        c.create_line(margin_l, margin_t, margin_l, h - margin_b, fill="#444466")
        c.create_line(margin_l, h - margin_b, w - margin_r, h - margin_b, fill="#444466")

        # -- x-axis labels (short date, skipped if too many sessions) --
        step = max(1, len(self._sessions) // 12)
        for i, s in enumerate(self._sessions):
            if i % step != 0 and i != len(self._sessions) - 1:
                continue
            lbl = s["date"][5:] if s["date"] else str(i + 1)  # "MM-DD"
            c.create_text(x_of(i), h - margin_b + 14, fill="#888899", font=("Consolas", 7), text=lbl, angle=0)

        # -- Selected session highlight (from the treeview) --
        selection = self._tree.selection()
        selected_i = int(selection[0]) if selection else None

        # -- Line + points --
        line_pts = []
        for i, v in points:
            line_pts.extend([x_of(i), y_of(v)])
        if len(points) >= 2:
            c.create_line(*line_pts, fill="#00cfff", width=2, smooth=False)

        for i, v in points:
            color = "#ffff00" if i == selected_i else "#00cfff"
            r = 5 if i == selected_i else 4
            c.create_oval(x_of(i) - r, y_of(v) - r, x_of(i) + r, y_of(v) + r, fill=color, outline="#ffffff")
            c.create_text(x_of(i), y_of(v) - 12, fill="#e0e0f0", font=("Consolas", 8), text=f"{v:.2f}")

        # -- Optional overlay: "Moyenne / tir" reference curve --
        # Shown on every chart except the "Moyenne / tir" one itself (where it
        # would just duplicate the main curve). Since this reference is in a
        # different unit (pts) than most displayed metrics (mm), it is scaled
        # independently to its own min/max and mapped into the same plot
        # area — only the shape/trend is comparable, not the absolute values.
        AVG_KEY = "average"
        if self._show_avg_var.get() and key != AVG_KEY:
            avg_points = [(i, s[AVG_KEY]) for i, s in enumerate(self._sessions) if s.get(AVG_KEY) is not None]
            if len(avg_points) >= 1:
                avg_vals = [v for _, v in avg_points]
                avg_min, avg_max = min(avg_vals), max(avg_vals)
                if avg_min == avg_max:
                    avg_min -= 1.0
                    avg_max += 1.0
                avg_pad = (avg_max - avg_min) * 0.12
                avg_min -= avg_pad
                avg_max += avg_pad

                # Higher score is always "good", so this overlay always uses
                # the default (non-inverted) top-is-better mapping, regardless
                # of the invert_axis setting used for the metric on display.
                def y_of_avg(v):
                    frac = (v - avg_min) / (avg_max - avg_min)
                    return margin_t + (h - margin_t - margin_b) * (1 - frac)

                if len(avg_points) >= 2:
                    avg_line_pts = []
                    for i, v in avg_points:
                        avg_line_pts.extend([x_of(i), y_of_avg(v)])
                    c.create_line(*avg_line_pts, fill="#888899", width=1, dash=(4, 3), smooth=False)

                c.create_text(w - margin_r, 10, anchor="ne", fill="#888899", font=("Consolas", 8), text="- - Moyenne / tir")

        c.create_text(margin_l, 10, anchor="nw", fill="#ffffff", font=("Consolas", 10, "bold"), text=f"{metric_label}  ({unit})  —  {len(points)} carton(s)")

        # -- Trend (simple linear regression over the plotted points) --
        if len(points) >= 2:
            xs = np.array(xs_idx, dtype=float)
            ys = np.array(ys_val, dtype=float)
            slope, intercept = np.polyfit(xs, ys, 1)
            mean_v = float(np.mean(ys))
            if higher_is_better is None:
                trend_color = "#e0e0f0"
            elif (slope > 0) == higher_is_better:
                trend_color = "#55ff55"
            else:
                trend_color = "#ff6666"
            self._trend_var.set(f"Moyenne sur la période : {mean_v:.2f} {unit}   |   " f"Tendance : {slope:+.3f} {unit}/carton")
            self._trend_lbl.config(fg=trend_color)
        else:
            self._trend_var.set(f"Valeur : {ys_val[0]:.2f} {unit}")
            self._trend_lbl.config(fg="#ffffff")


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------


class TargetApp(tk.Tk):
    def __init__(self, initial_path: str | None = None):
        super().__init__()
        self.title("TirMetrix - Analyse de cible ISSF C50 pour tir à 25 m")
        self._set_app_icon()
        self.configure(bg="#0f0f14")
        self.minsize(1050, 612)
        self.resizable(True, True)
        self._center_window(1700, 1225)

        # --- State ---
        self._img_orig: np.ndarray | None = None  # original full-res image
        self._pil_orig: Image.Image | None = None
        self._display_img: ImageTk.PhotoImage | None = None
        self._image_stem: str = "cible"  # filename without extension, used for export defaults

        # Calibration (in original image pixels).
        # The target rings are perfect circles in physical space (250 mm, etc.)
        # but may appear as ellipses in the image if the photo was not taken
        # perfectly square-on or if perspective correction introduced aspect-ratio
        # distortion.  We therefore keep independent horizontal and vertical
        # mm/px scales so that the ring overlays always match the actual rings.
        self._center_orig: tuple[float, float] | None = None  # (cx, cy) px
        self._mpp_x: float | None = None  # mm per pixel, horizontal axis
        self._mpp_y: float | None = None  # mm per pixel, vertical axis

        # Impacts: list of (x_orig, y_orig) in original image coordinates
        self._impacts: list[tuple[float, float]] = []
        self._selected_idx: int | None = None  # index of selected impact

        # Canvas display scaling
        self._scale: float = 1.0  # orig_px * scale = canvas_px
        self._offset: tuple[float, float] = (0.0, 0.0)  # canvas origin of image top-left

        # Interaction mode
        self._mode = "add"  # "add" | "delete" | "move"
        self._drag_start: tuple[float, float] | None = None

        # Overlay toggles
        self._show_axis = tk.BooleanVar(value=False)
        self._show_cep50 = tk.BooleanVar(value=True)  # CEP 50 circle (median radial error)
        self._show_cep90 = tk.BooleanVar(value=True)  # CEP 90 circle (90th-percentile radial error)
        self._show_mec = tk.BooleanVar(value=False)  # MEC circle (smallest circle enclosing all impacts)

        # Manual calibration state: None | "ring1_pts"
        # User clicks 3+ points on the outer edge of ring 1; centre + scale are
        # computed via algebraic least-squares circle fit (no need to click centre).
        self._manual_calib_step: str | None = None
        self._manual_calib_pts: list[tuple[float, float]] = []  # ring-1 edge clicks

        # Perspective correction state: None | "corner" (clicking 4 corners)
        self._persp_step: int | None = None  # 0-3: which corner we're waiting for
        self._persp_corners: list[tuple[float, float]] = []  # collected corners (canvas px)
        self._persp_circle_pos: tuple[int, int] | None = None  # cursor ring overlay position
        # Physical card size (width, height) in mm chosen in the "Calibrer le
        # carton" dialog; remembered between calibrations.
        self._card_size_mm: tuple[float, float] = (CARD_WIDTH_MM, CARD_HEIGHT_MM)

        # Active caliber (bullet radius used for scoring)
        self._caliber_var = tk.StringVar(value=CALIBER_DEFAULT)

        self._build_ui()

        if initial_path:
            self.after(100, lambda: self._load_image(initial_path))

    # ------------------------------------------------------------------
    # Calibration helpers
    # ------------------------------------------------------------------

    @property
    def _mm_per_px_orig(self) -> float | None:
        """Isotropic mm/px (geometric mean of x and y scales).
        Used only where a single distance is needed (CEP, mean radius…).
        Scoring and ring drawing always use _mpp_x / _mpp_y directly."""
        if self._mpp_x is None or self._mpp_y is None:
            return None
        return (self._mpp_x + self._mpp_y) / 2.0

    def _is_calibrated(self) -> bool:
        return self._center_orig is not None and self._mpp_x is not None and self._mpp_y is not None

    def _set_calib(self, cx: float, cy: float, mpp_x: float, mpp_y: float, label: str):
        """Apply new calibration values and refresh the display."""
        self._center_orig = (cx, cy)
        self._mpp_x = mpp_x
        self._mpp_y = mpp_y
        ratio = mpp_y / mpp_x if mpp_x else 1.0
        self._calib_var.set(
            f"Centre : ({cx:.0f}, {cy:.0f}) px\n" f"Éch. X : {mpp_x:.4f} mm/px\n" f"Éch. Y : {mpp_y:.4f} mm/px\n" f"Rapport H/L : {ratio:.4f}\n" f"({label})"
        )

    # ------------------------------------------------------------------
    # Centre the window
    # ------------------------------------------------------------------

    def _center_window(self, width=1400, height=850):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _set_app_icon(self):
        """Apply the application icon to the window (and its dialogs/toplevels).
        Kept non-fatal: a missing/unreadable icon file must never prevent the
        app from starting."""
        try:
            icon_path = resource_path("target_32.png")
            self._icon_img = ImageTk.PhotoImage(Image.open(icon_path))  # kept as attribute to avoid GC
            self.iconphoto(True, self._icon_img)
        except Exception:
            pass  # non-fatal — app still runs fine without a custom icon

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        main = tk.Frame(self, bg="#0f0f14")
        main.pack(fill=tk.BOTH, expand=True)

        tools = tk.Frame(main, bg="#1a1a24", width=190)
        tools.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 2))
        tools.pack_propagate(False)

        self._build_tool_panel(tools)

        left = tk.Frame(main, bg="#12121c", width=260)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(2, 2))
        left.pack_propagate(False)

        self._build_left_panel(left)

        canvas_frame = tk.Frame(main, bg="#0f0f14")
        canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(canvas_frame, bg="#0a0a10", highlightthickness=0, cursor="crosshair")
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Configure>", self._on_resize)
        self._canvas.bind("<ButtonPress-1>", self._on_click)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Motion>", self._on_mouse_move)
        self._canvas.bind("<MouseWheel>", self._on_scroll)
        self._canvas.bind("<Button-4>", self._on_scroll)
        self._canvas.bind("<Button-5>", self._on_scroll)

        right = tk.Frame(main, bg="#12121c", width=260)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(2, 4))
        right.pack_propagate(False)

        self._build_right_panel(right)

        self._hint_lbl = tk.Label(canvas_frame, text="Charger une image pour commencer", bg="#0a0a10", fg="#ffffff", font=("Consolas", 9))
        self._hint_lbl.place(relx=0.5, rely=0.04, anchor="s")

    def _build_tool_panel(self, parent: tk.Frame):
        """Vertical toolbar on the far left of the window. Buttons are
        grouped into visually distinct, tinted zones (rather than a flat
        list) so related actions read together at a glance, and stacked
        rather than laid out horizontally so the window can be narrowed
        without buttons overflowing or being clipped."""

        def btn(parent, text, cmd, bg="#30304a", fg="#e0e0f0"):
            b = tk.Button(
                parent,
                text=text,
                command=cmd,
                bg=bg,
                fg=fg,
                relief=tk.FLAT,
                anchor="w",
                font=("Consolas", 9, "bold"),
                padx=10,
                pady=6,
                cursor="hand2",
                activebackground="#50508a",
                activeforeground="#ffffff",
            )
            b.pack(fill=tk.X, pady=2)
            return b

        def group(bg):
            """A tinted card-like container holding one logical group of
            controls; the tint makes the grouping visible at a glance."""
            g = tk.Frame(parent, bg=bg, padx=6, pady=8)
            g.pack(fill=tk.X, padx=6, pady=(0, 10))
            return g

        # -- Group 1: session -------------------------------------------------
        g_session = group("#17233a")
        btn(g_session, "Nouvelle cible", self._open_dialog, bg="#3a6fd8")
        btn(g_session, "Reprendre cible", self._import_json, bg="#3a6fd8")

        # -- Group 2: calibration / centering ----------------------------------
        g_calib = group("#1c2536")
        btn(g_calib, "Calibrer le carton", self._start_persp_click, bg="#2c5b76")
        btn(g_calib, "Calibrer la zone 1", self._start_manual_calib, bg="#2c5b76")
        btn(g_calib, "Centrer le carton", self._recentre, bg="#2c5b76")
        btn(g_calib, "Exporter tout", self._export_all, bg="#2a6a5a")

        # -- Group 3: marking modes + edition -----------------------------------
        g_mark = group("#242030")

        self._mode_var = tk.StringVar(value="add")

        def mode_radio(text, value):
            r = tk.Radiobutton(
                g_mark,
                text=text,
                variable=self._mode_var,
                value=value,
                command=self._on_mode_change,
                bg="#242030",
                fg="#b0b0d0",
                selectcolor="#2a2a40",
                activebackground="#242030",
                activeforeground="#ffffff",
                font=("Consolas", 9),
                relief=tk.FLAT,
                anchor="w",
                padx=6,
            )
            r.pack(fill=tk.X)

        mode_radio("Ajouter", "add")
        mode_radio("Supprimer", "delete")
        mode_radio("Déplacer", "move")

        tk.Frame(g_mark, bg="#3a3550", height=1).pack(fill=tk.X, pady=6)

        btn(g_mark, "Annuler", self._undo, bg="#555570")
        btn(g_mark, "Tout effacer", self._clear_all, bg="#7a2a2a")

        # -- Group 4: history -----------------------------------------------------
        g_history = group("#2a2410")
        btn(g_history, "Historique", self._open_history, bg="#8a6a2a")
        btn(g_history, "Stabilité balle", self._open_stability, bg="#5a3a8a")

    def _build_left_panel(self, parent: tk.Frame):
        self._path_lbl = tk.Label(parent, text="Aucune image chargée", bg="#12121c", fg="#ffffff", font=("Consolas", 8), anchor="w", wraplength=235)
        self._path_lbl.pack(fill=tk.X, padx=12, pady=(6, 0))

        def section(text):
            lbl = tk.Label(parent, text=text, bg="#12121c", fg="#55ff55", font=("Consolas", 8), anchor="w")
            lbl.pack(fill=tk.X, padx=12, pady=(10, 1))
            _attach_tooltip(lbl, text)
            tk.Frame(parent, bg="#222235", height=1).pack(fill=tk.X, padx=12)

        counter_frame = tk.Frame(parent, bg="#1e1e30", pady=12)
        counter_frame.pack(fill=tk.X, padx=10, pady=(14, 4))

        # --- Caliber selector ---
        cal_frame = tk.Frame(parent, bg="#12121c")
        cal_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
        tk.Label(cal_frame, text="CALIBRE", bg="#12121c", fg="#55ff55", font=("Consolas", 8), anchor="w").pack(anchor="w", padx=2)
        caliber_cb = tk.OptionMenu(cal_frame, self._caliber_var, *CALIBERS.keys(), command=lambda _: (self._redraw(), self._update_stats()))
        caliber_cb.config(
            bg="#2a2a40",
            fg="#e0e0f0",
            relief=tk.FLAT,
            font=("Consolas", 9),
            activebackground="#50508a",
            activeforeground="#ffffff",
            highlightthickness=0,
            anchor="w",
            width=18,
        )
        caliber_cb["menu"].config(bg="#2a2a40", fg="#e0e0f0", font=("Consolas", 9))
        caliber_cb.pack(fill=tk.X, padx=2)

        tk.Label(counter_frame, text="IMPACTS MARQUÉS", bg="#1e1e30", fg="#ffffff", font=("Consolas", 7)).pack()
        self._counter_var = tk.StringVar(value="0")
        tk.Label(counter_frame, textvariable=self._counter_var, bg="#1e1e30", fg="#ffffff", font=("Consolas", 42, "bold")).pack()

        section("RÉSUMÉ")
        self._svars: dict[str, tk.StringVar] = {}
        rows = [
            ("total", "Score total"),
            ("avg", "Moyenne / tir"),
            ("best", "Meilleur"),
            ("worst", "Plus mauvais"),
            ("std", "Écart-type"),
            ("pct_max", "% du score max"),
        ]
        for key, label in rows:
            row = tk.Frame(parent, bg="#12121c")
            row.pack(fill=tk.X, padx=12, pady=1)
            name_lbl = tk.Label(row, text=label, bg="#12121c", fg="#ffffff", font=("Consolas", 8), anchor="w")
            name_lbl.pack(side=tk.LEFT)
            _attach_tooltip(name_lbl, label)
            v = tk.StringVar(value="—")
            self._svars[key] = v
            tk.Label(row, textvariable=v, bg="#12121c", fg="#ffffff", font=("Consolas", 9, "bold"), anchor="e").pack(side=tk.RIGHT)

        section("RÉPARTITION PAR BAGUE")
        self._ring_vars: dict[int, tk.StringVar] = {}
        for ring in sorted(RINGS_MM.keys(), reverse=True):
            row = tk.Frame(parent, bg="#12121c")
            row.pack(fill=tk.X, padx=12, pady=1)
            dot = tk.Label(row, text="●", bg="#12121c", fg=RING_COLORS.get(ring, "#888888"), font=("Consolas", 8))
            dot.pack(side=tk.LEFT)
            tk.Label(row, text=f" {ring:2d}", bg="#12121c", fg="#ffffff", font=("Consolas", 9), anchor="w").pack(side=tk.LEFT)
            v = tk.StringVar(value="—")
            self._ring_vars[ring] = v
            tk.Label(row, textvariable=v, bg="#12121c", fg="#ffffff", font=("Consolas", 9), anchor="e").pack(side=tk.RIGHT)

        section("FIABILITÉ (N tirs)")
        self._nstat_vars: dict[str, tk.StringVar] = {}
        n_rows = [
            ("n_tirs", "N tirs"),
            ("score_eq10", "Score éq. / 10 tirs"),
            ("mean_ci", "IC moyenne à 95 %"),
            ("flyers", "Flyers détectés"),
            ("flyer_rate", "Taux de flyers"),
            ("flyer_ci", "IC taux flyers"),
            ("flyer_risk", "Risque d'≥1 flyer"),
            ("shots_bf", "Tirs moyens avant flyer"),
        ]
        for key, label in n_rows:
            row = tk.Frame(parent, bg="#12121c")
            row.pack(fill=tk.X, padx=12, pady=1)
            name_lbl = tk.Label(row, text=label, bg="#12121c", fg="#ffffff", font=("Consolas", 8), anchor="w")
            name_lbl.pack(side=tk.LEFT)
            _attach_tooltip(name_lbl, label)
            v = tk.StringVar(value="—")
            self._nstat_vars[key] = v
            tk.Label(row, textvariable=v, bg="#12121c", fg="#ffffff", font=("Consolas", 9, "bold"), anchor="e").pack(side=tk.RIGHT)

        section("CALIBRATION")
        self._calib_var = tk.StringVar(value="—")
        tk.Label(parent, textvariable=self._calib_var, bg="#12121c", fg="#ffffff", font=("Consolas", 8), justify="left", wraplength=210, anchor="w").pack(
            fill=tk.X, padx=12, pady=3
        )

        section("CURSEUR")
        self._cursor_var = tk.StringVar(value="—")
        tk.Label(parent, textvariable=self._cursor_var, bg="#12121c", fg="#ffffff", font=("Consolas", 8), anchor="w", justify="left", wraplength=235).pack(
            fill=tk.X, padx=12, pady=3
        )

    def _build_right_panel(self, parent: tk.Frame):
        def section(text):
            lbl = tk.Label(parent, text=text, bg="#12121c", fg="#ff5555", font=("Consolas", 8, "bold"), anchor="w")
            lbl.pack(fill=tk.X, padx=12, pady=(10, 1))
            _attach_tooltip(lbl, text)
            tk.Frame(parent, bg="#222235", height=1).pack(fill=tk.X, padx=12)

        # --- Overlay toggles ---
        section("AFFICHAGE")

        def chk(text, var):
            cb = tk.Checkbutton(
                parent,
                text=text,
                variable=var,
                command=self._redraw,
                bg="#12121c",
                fg="#ffffff",
                selectcolor="#1e1e30",
                activebackground="#12121c",
                activeforeground="#ffffff",
                font=("Consolas", 9),
            )
            cb.pack(anchor="w", padx=14, pady=1)
            _attach_tooltip(cb, text)

        chk("Axe de dispersion (PCA)", self._show_axis)
        chk("Cercle CEP 50 (groupement)", self._show_cep50)
        chk("Cercle CEP 90 (groupement)", self._show_cep90)
        chk("Cercle MEC (groupement)", self._show_mec)

        def stat_row(store: dict, key: str, label: str):
            """Row with a name (tooltip-enabled) and a bold value, used for
            every individual statistic in the right panel."""
            row = tk.Frame(parent, bg="#12121c")
            row.pack(fill=tk.X, padx=12, pady=1)
            name_lbl = tk.Label(row, text=label, bg="#12121c", fg="#ffffff", font=("Consolas", 8), anchor="w")
            name_lbl.pack(side=tk.LEFT)
            _attach_tooltip(name_lbl, label)
            v = tk.StringVar(value="—")
            store[key] = v
            tk.Label(row, textvariable=v, bg="#12121c", fg="#ffffff", font=("Consolas", 9, "bold"), anchor="e").pack(side=tk.RIGHT)

        section("DISPERSION")
        self._disp_vars: dict[str, tk.StringVar] = {}
        stat_row(self._disp_vars, "mean_r", "Rayon moyen")
        stat_row(self._disp_vars, "std_r", "Écart-type rayon")
        stat_row(self._disp_vars, "std_x", "Écart-type X")
        stat_row(self._disp_vars, "std_y", "Écart-type Y")

        section("GROUPEMENT")
        self._group_vars: dict[str, tk.StringVar] = {}
        stat_row(self._group_vars, "max_pair", "Diamètre max")
        stat_row(self._group_vars, "mec_diam", "Diamètre MEC")

        section("DÉCALAGE MOYEN")
        self._bias_vars: dict[str, tk.StringVar] = {}
        stat_row(self._bias_vars, "dx", "ΔX moyen")
        stat_row(self._bias_vars, "dy", "ΔY moyen")

        section("CEP — GROUPEMENT (dispersion)")
        self._cep_group_vars: dict[str, tk.StringVar] = {}
        stat_row(self._cep_group_vars, "cep50", "CEP 50 (groupement)")
        stat_row(self._cep_group_vars, "cep90", "CEP 90 (groupement)")

        section("CEP — POINT VISÉ (centrage)")
        self._cep_poi_vars: dict[str, tk.StringVar] = {}
        stat_row(self._cep_poi_vars, "cep50", "CEP 50 (point visé)")
        stat_row(self._cep_poi_vars, "cep90", "CEP 90 (point visé)")
        stat_row(self._cep_poi_vars, "mean_r", "Rayon moyen (point visé)")
        stat_row(self._cep_poi_vars, "std_r", "Écart-type rayon (point visé)")

        section("ELLIPSE")
        self._ellipse_vars: dict[str, tk.StringVar] = {}
        stat_row(self._ellipse_vars, "major", "Axe majeur")
        stat_row(self._ellipse_vars, "minor", "Axe mineur")
        stat_row(self._ellipse_vars, "aspect", "Rapport d'aspect")
        stat_row(self._ellipse_vars, "angle", "Angle")

        section("CONSISTANCE")
        self._consistency_vars: dict[str, tk.StringVar] = {}
        stat_row(self._consistency_vars, "cv", "Coef. variation (rayon)")

    # ------------------------------------------------------------------
    # File loading & calibration
    # ------------------------------------------------------------------

    def _open_dialog(self):
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        path = filedialog.askopenfilename(
            title="Ouvrir une photo de cible",
            initialdir=downloads if os.path.isdir(downloads) else "~",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"), ("Tous", "*.*")],
        )
        if path:
            self._load_image(path)

    def _load_image(self, path: str):
        img = cv2.imread(path)
        if img is None:
            messagebox.showerror("Erreur", f"Impossible de charger :\n{path}")
            return
        self._impacts.clear()
        self._selected_idx = None
        self._image_stem = os.path.splitext(os.path.basename(path))[0]
        self._path_lbl.config(text=os.path.basename(path))

        # --- Attempt automatic perspective correction ---
        corners = detect_target_corners(img)
        if corners is not None:
            img = correct_perspective(img, corners)
            # Show a brief notice but don't block
            self._hint_lbl.config(text="Perspective corrigée automatiquement  |  Clic gauche → ajouter un impact", fg="#55ff55")
            self.after(3000, lambda: self._hint_lbl.config(text="Clic gauche → ajouter un impact  |  Molette → zoom", fg="#ffffff"))
        else:
            # Auto-detection failed — prompt user to correct manually
            self._hint_lbl.config(text="⚠ Perspective non détectée. Utilisez 'Calibrer le carton' si nécessaire.", fg="#ffaa44")
            self.after(5000, lambda: self._hint_lbl.config(text="Clic gauche → ajouter un impact  |  Molette → zoom", fg="#ffffff"))

        self._img_orig = img
        self._pil_orig = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        self._calibrate()
        self._fit_to_canvas()
        self._redraw()
        self._update_stats()

    def _calibrate(self):
        """Auto-detect target centre and mm/px scale from the loaded image.

        Calibration strategy (in priority order):
          1. Radial edge-profile match on rings 1 & 2 (most robust, ignores
             any reactive target on the black disc area).
          2. Black disc outer edge (ring 6/7 boundary, 125 mm) — fallback.
        Centre is refined by the red aiming-dot detector when available.
        """
        if self._img_orig is None:
            return

        center = detect_target_center(self._img_orig)

        # --- Primary: rings 1 & 2 via radial edge profile ---
        result = detect_rings_1_and_2(self._img_orig)
        if result is not None:
            auto_cx, auto_cy, mpp = result
            cx, cy = center if center else (auto_cx, auto_cy)
            self._set_calib(cx, cy, mpp, mpp, "auto — bagues 1 & 2")
            return

        # --- Fallback: black disc ---
        disc = detect_black_disc(self._img_orig)
        if disc is None:
            messagebox.showwarning("Calibration", "Cible non détectée. Utilisez le calibrage manuel.")
            self._center_orig = None
            self._mpp_x = None
            self._mpp_y = None
            self._calib_var.set("Non calibré")
            return
        dcx, dcy, black_r = disc
        cx, cy = center if center else (dcx, dcy)
        mpp_disc = 125.0 / black_r
        self._set_calib(cx, cy, mpp_disc, mpp_disc, "auto — disque noir")

    def _recentre(self):
        """Refit the view so the target is centred and fills the canvas.

        Does NOT touch the calibration — centre, mpp_x and mpp_y are preserved.
        Use this after a zoom/pan to snap back to the full-image view.
        """
        self._fit_to_canvas()
        self._redraw()
        self._update_stats()

    # ------------------------------------------------------------------
    # History / evolution across multiple exported targets
    # ------------------------------------------------------------------

    def _open_history(self):
        """Ask the user for a folder, scan it for exported '*_data.json'
        session files, and open the History window showing the evolution
        of the shooter's statistics across all the targets found."""
        downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        folder = filedialog.askdirectory(
            title="Choisir le dossier contenant les exports (cartons)",
            initialdir=downloads if os.path.isdir(downloads) else "~",
        )
        if not folder:
            return

        sessions, n_errors = scan_export_folder(folder)
        if not sessions:
            messagebox.showinfo("Historique", f"Aucun export ({'*_data.json'}) trouvé dans :\n{folder}")
            return
        if n_errors:
            messagebox.showwarning("Historique", f"{n_errors} fichier(s) n'ont pas pu être lus et ont été ignorés.")

        HistoryWindow(self, folder, sessions)

    def _open_stability(self):
        """Open the gyroscopic stability (SG, Miller formula) calculator."""
        StabilityWindow(self)

    # ------------------------------------------------------------------
    # Canvas / viewport helpers
    # ------------------------------------------------------------------

    def _fit_to_canvas(self):
        """Scale image so it fits the current canvas, centred."""
        if self._pil_orig is None:
            return
        cw = self._canvas.winfo_width() or 900
        ch = self._canvas.winfo_height() or 700
        iw, ih = self._pil_orig.size
        self._scale = min(cw / iw, ch / ih) * 0.96
        self._offset = ((cw - iw * self._scale) / 2, (ch - ih * self._scale) / 2)

    def _orig_to_canvas(self, x: float, y: float) -> tuple[float, float]:
        ox, oy = self._offset
        return ox + x * self._scale, oy + y * self._scale

    def _canvas_to_orig(self, cx: float, cy: float) -> tuple[float, float]:
        ox, oy = self._offset
        return (cx - ox) / self._scale, (cy - oy) / self._scale

    def _orig_dist_mm(self, x: float, y: float) -> float | None:
        """Isotropic distance in mm from target centre (geometric-mean scale)."""
        if not self._is_calibrated():
            return None
        cx, cy = self._center_orig
        dx_mm = (x - cx) * self._mpp_x
        dy_mm = (y - cy) * self._mpp_y
        return math.hypot(dx_mm, dy_mm)

    def _score_at_orig(self, x: float, y: float) -> int:
        if not self._is_calibrated():
            return 0
        cx, cy = self._center_orig
        # Convert pixel offset to mm using per-axis scales, then test against
        # the normalised ellipse equation: (dx/rx)²+(dy/ry)² ≤ 1, where
        # rx = ring_mm/mpp_x and ry = ring_mm/mpp_y.
        # Equivalently, compute the "normalised" distance:
        #   d_norm = sqrt((dx_px * mpp_x)² + (dy_px * mpp_y)²)
        # which equals the physical mm distance on an isotropic target.
        dx_mm = (x - cx) * self._mpp_x
        dy_mm = (y - cy) * self._mpp_y
        # ISSF rule: nearest edge of the bullet hole decides the score.
        bullet_radius = CALIBERS.get(self._caliber_var.get(), 0.0)
        dist = max(0.0, math.hypot(dx_mm, dy_mm) - bullet_radius)
        for score in sorted(RINGS_MM, reverse=True):
            if dist <= RINGS_MM[score]:
                return score
        return 0

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _redraw(self):
        if self._pil_orig is None:
            return
        c = self._canvas
        c.delete("all")

        # Draw image
        iw, ih = self._pil_orig.size
        disp_w = max(1, int(iw * self._scale))
        disp_h = max(1, int(ih * self._scale))
        resized = self._pil_orig.resize((disp_w, disp_h), Image.LANCZOS).convert("RGBA")
        ox, oy = self._offset

        # Real alpha-blended fill for the CEP 50 / CEP 90 discs, baked into
        # the displayed image itself. Tk canvas "stipple" fills are not
        # reliably translucent across platforms (often render as solid), so
        # true compositing is used instead for a dependable ~20% tint.
        if self._is_calibrated() and len(self._impacts) >= 1 and (self._show_cep50.get() or self._show_cep90.get()):
            cx0, cy0 = self._center_orig
            cdxs = np.array([(x - cx0) * self._mpp_x for x, y in self._impacts], dtype=float)
            cdys = np.array([(y - cy0) * self._mpp_y for x, y in self._impacts], dtype=float)
            cmean_dx, cmean_dy = float(cdxs.mean()), float(cdys.mean())
            ccentered = np.sqrt((cdxs - cmean_dx) ** 2 + (cdys - cmean_dy) ** 2)
            mpp_avg = self._mm_per_px_orig or 1.0
            # Group centre, in resized-image-local pixel coordinates (i.e.
            # canvas coords minus the pan offset — no "- ox/oy" needed here
            # since that offset never enters this local-pixel space).
            cscx = (cx0 + cmean_dx / self._mpp_x) * self._scale
            cscy = (cy0 + cmean_dy / self._mpp_y) * self._scale

            tint = Image.new("RGBA", resized.size, (0, 0, 0, 0))
            tdraw = ImageDraw.Draw(tint)
            alpha = 51  # ~20% of 255

            if self._show_cep90.get() and len(self._impacts) >= 2:
                cep90 = cep_from_distances(ccentered, 90)
                r90_px = cep90 / mpp_avg * self._scale
                tdraw.ellipse([cscx - r90_px, cscy - r90_px, cscx + r90_px, cscy + r90_px], fill=(255, 68, 204, alpha))

            if self._show_cep50.get() and len(self._impacts) >= 1:
                cep50 = cep_from_distances(ccentered, 50)
                r50_px = cep50 / mpp_avg * self._scale
                tdraw.ellipse([cscx - r50_px, cscy - r50_px, cscx + r50_px, cscy + r50_px], fill=(0, 207, 255, alpha))

            resized = Image.alpha_composite(resized, tint)

        self._display_img = ImageTk.PhotoImage(resized)
        c.create_image(ox, oy, anchor="nw", image=self._display_img)

        # Draw ring overlays — ellipses when mpp_x ≠ mpp_y
        if self._is_calibrated():
            cx, cy = self._center_orig
            scx, scy = self._orig_to_canvas(cx, cy)
            for ring, r_mm in RINGS_MM.items():
                # Independent radii per axis
                rx_scr = (r_mm / self._mpp_x) * self._scale
                ry_scr = (r_mm / self._mpp_y) * self._scale
                color = RING_COLORS.get(ring, "#888888")
                c.create_oval(scx - rx_scr, scy - ry_scr, scx + rx_scr, scy + ry_scr, outline=color, width=3, dash=(4, 6), tags="ring")
        else:
            scx = scy = 0  # fallback so crosshair lines below don't crash
        # Centre crosshair
        c.create_line(scx - 14, scy, scx + 14, scy, fill="#40ff40", width=2, tags="center")
        c.create_line(scx, scy - 14, scx, scy + 14, fill="#40ff40", width=2, tags="center")

        # Draw statistical overlays (CEP/MEC circles, PCA axis) BEFORE the
        # impacts themselves, so the impact dots stay fully visible on top
        # of the (lightly tinted) circles rather than being covered by them.
        self._draw_overlays()

        # Draw impacts — circle radius matches actual bullet size on screen
        bullet_radius_mm = CALIBERS.get(self._caliber_var.get(), 4.5)
        r_base = IMPACT_RADIUS_SCREEN  # fallback if not calibrated

        # Flag flyer impacts (radial outliers from the group barycentre) so
        # they can be highlighted — same rule as the "Flyers détectés" stat.
        flyer_mask = None
        if self._is_calibrated() and len(self._impacts) >= 2:
            fdx = np.array([(x - cx) * self._mpp_x for x, y in self._impacts], dtype=float)
            fdy = np.array([(y - cy) * self._mpp_y for x, y in self._impacts], dtype=float)
            fcentered = np.sqrt((fdx - fdx.mean()) ** 2 + (fdy - fdy.mean()) ** 2)
            flyer_mask = detect_flyers(fcentered)

        for idx, (ix, iy) in enumerate(self._impacts):
            sx, sy = self._orig_to_canvas(ix, iy)
            score = self._score_at_orig(ix, iy)
            is_sel = idx == self._selected_idx
            border = IMPACT_SELECTED if is_sel else IMPACT_BORDER
            bw = 3 if is_sel else 2
            # Scale bullet radius from mm to screen pixels (use average scale)
            r = max(4, int(bullet_radius_mm / self._mpp_x * self._scale)) if self._mpp_x else r_base
            c.create_oval(sx - r, sy - r, sx + r, sy + r, fill=IMPACT_COLOR, outline=border, width=bw, tags=("impact", f"impact_{idx}"))
            c.create_text(sx, sy - r - 7, text=str(score), fill="#ffffff" if not is_sel else "#ffff80", font=("Consolas", 8, "bold"), tags="label")
            if flyer_mask is not None and flyer_mask[idx]:
                c.create_oval(
                    sx - r - 6, sy - r - 6, sx + r + 6, sy + r + 6, outline="#ff2222", width=2, dash=(3, 2), tags=("impact", f"impact_{idx}", "flyer")
                )

        self._update_hint()

    def _draw_overlays(self):
        """Draw optional statistical overlays: MEC circle and PCA dispersion axis."""
        if len(self._impacts) < 2:
            return
        if not self._is_calibrated():
            return

        cx0, cy0 = self._center_orig
        mpp = self._mm_per_px_orig  # isotropic average, for MEC radius px conversion
        c = self._canvas

        # Build (N, 2) array of impact positions in mm relative to target centre
        dxs = np.array([(x - cx0) * self._mpp_x for x, y in self._impacts])
        dys = np.array([(y - cy0) * self._mpp_y for x, y in self._impacts])
        pts_mm = np.column_stack((dxs, dys))

        # Helper: convert mm-from-centre to canvas pixels (per-axis scales)
        def mm_to_canvas(dx_mm, dy_mm):
            ox = cx0 + dx_mm / self._mpp_x
            oy = cy0 + dy_mm / self._mpp_y
            return self._orig_to_canvas(ox, oy)

        # --- PCA dispersion axis (principal eigenvector) ---
        if self._show_axis.get() and len(self._impacts) >= 2:
            cov = np.cov(pts_mm.T)
            eigvals, eigvecs = np.linalg.eigh(cov)
            order = np.argsort(eigvals)[::-1]
            eigvals = eigvals[order]
            eigvecs = eigvecs[:, order]

            # Semi-axes lengths: 2σ along each eigenvector
            a = float(2.0 * np.sqrt(max(eigvals[0], 0.0)))  # major (mm)
            b = float(2.0 * np.sqrt(max(eigvals[1], 0.0)))  # minor (mm)
            v_major = eigvecs[:, 0]  # unit vector, major axis
            v_minor = eigvecs[:, 1]  # unit vector, minor axis

            mean_dx, mean_dy = float(np.mean(dxs)), float(np.mean(dys))

            # Draw ellipse via a sampled polygon on the canvas
            N_seg = 72
            angles = np.linspace(0, 2 * math.pi, N_seg, endpoint=False)
            ellipse_pts = []
            for angle in angles:
                ex = mean_dx + a * math.cos(angle) * v_major[0] + b * math.sin(angle) * v_minor[0]
                ey = mean_dy + a * math.cos(angle) * v_major[1] + b * math.sin(angle) * v_minor[1]
                sx, sy = mm_to_canvas(ex, ey)
                ellipse_pts += [sx, sy]
            c.create_polygon(ellipse_pts, outline="#ff8800", fill="", width=4, dash=(6, 4), tags="overlay")

            # Major axis line: from -a to +a along eigenvector, through mean
            p1x, p1y = mm_to_canvas(mean_dx - a * v_major[0], mean_dy - a * v_major[1])
            p2x, p2y = mm_to_canvas(mean_dx + a * v_major[0], mean_dy + a * v_major[1])
            c.create_line(p1x, p1y, p2x, p2y, fill="#ff8800", width=3, arrow=tk.BOTH, arrowshape=(6, 8, 3), tags="overlay")

            # Minor axis line
            q1x, q1y = mm_to_canvas(mean_dx - b * v_minor[0], mean_dy - b * v_minor[1])
            q2x, q2y = mm_to_canvas(mean_dx + b * v_minor[0], mean_dy + b * v_minor[1])
            c.create_line(q1x, q1y, q2x, q2y, fill="#ffbb44", width=1, dash=(4, 4), tags="overlay")

            # Mean point marker
            mscx, mscy = mm_to_canvas(mean_dx, mean_dy)
            arm = 5
            c.create_line(mscx - arm, mscy, mscx + arm, mscy, fill="#ff8800", width=4, tags="overlay")
            c.create_line(mscx, mscy - arm, mscx, mscy + arm, fill="#ff8800", width=4, tags="overlay")

            # Label: angle of major axis relative to vertical (Y-axis = up on target)
            angle_deg = float(np.degrees(np.arctan2(v_major[0], -v_major[1]))) % 180
            c.create_text(p2x + 6, p2y, text=f"{angle_deg:.1f}°\n2σ={a:.1f}mm", fill="#ff8800", font=("Consolas", 7), anchor="w", tags="overlay")

        # --- CEP circles (centred on group mean, not on target centre) ---
        # CEP50 / CEP90 are computed from centred radial distances so that
        # a systematically biased group is evaluated for its internal dispersion.
        if (self._show_cep50.get() or self._show_cep90.get()) and len(self._impacts) >= 2:
            mean_dx = float(np.mean(dxs))
            mean_dy = float(np.mean(dys))
            # Radial distances from group barycentre (in mm)
            centered = np.sqrt((pts_mm[:, 0] - mean_dx) ** 2 + (pts_mm[:, 1] - mean_dy) ** 2)
            mscx, mscy = mm_to_canvas(mean_dx, mean_dy)
            mpp = self._mm_per_px_orig or 1.0

            if self._show_cep50.get() and len(self._impacts) >= 1:
                cep50 = cep_from_distances(centered, 50)
                r50_px = cep50 / mpp * self._scale
                c.create_oval(
                    mscx - r50_px,
                    mscy - r50_px,
                    mscx + r50_px,
                    mscy + r50_px,
                    outline="#00cfff",
                    width=4,
                    dash=(6, 4),
                    tags="overlay",
                )
                # "(grp)" = centred on group barycentre, not on the point of
                # aim — see CEP — GROUPEMENT vs CEP — POINT VISÉ in the panel.
                c.create_text(mscx, mscy - r50_px - 8, text="CEP 50 (grp)", fill="#00cfff", font=("Consolas", 8), tags="overlay")

            if self._show_cep90.get() and len(self._impacts) >= 2:
                cep90 = cep_from_distances(centered, 90)
                r90_px = cep90 / mpp * self._scale
                c.create_oval(
                    mscx - r90_px,
                    mscy - r90_px,
                    mscx + r90_px,
                    mscy + r90_px,
                    outline="#ff44cc",
                    width=4,
                    dash=(4, 6),
                    tags="overlay",
                )
                c.create_text(mscx, mscy - r90_px - 8, text="CEP 90 (grp)", fill="#ff44cc", font=("Consolas", 8), tags="overlay")

        # --- MEC circle (smallest circle enclosing every impact) ---
        if self._show_mec.get() and len(self._impacts) >= 2:
            mec_cx, mec_cy, mec_r = minimum_enclosing_circle(pts_mm)
            mec_scx, mec_scy = mm_to_canvas(mec_cx, mec_cy)
            mec_r_px = mec_r / (mpp or 1.0) * self._scale
            c.create_oval(
                mec_scx - mec_r_px, mec_scy - mec_r_px, mec_scx + mec_r_px, mec_scy + mec_r_px, outline="#00ee44", width=3, tags="overlay"
            )
            c.create_text(mec_scx, mec_scy - mec_r_px - 8, text="MEC (grp)", fill="#00ee44", font=("Consolas", 8), tags="overlay")

    def _update_hint(self):
        # A calibration procedure in progress owns the hint text: any redraw
        # (re-centre, zoom, resize...) must not replace it with the
        # "add an impact" hint before the procedure is finished.
        if self._persp_step is not None:
            self._update_persp_hint()
            return
        if self._manual_calib_step is not None:
            n = len(self._manual_calib_pts)
            if n == 0:
                text = "CALIBRAGE — Clics sur le bord de la ZONE 1 (≥ 3)  |  Clic droit ou Entrée pour valider"
            else:
                text = f"CALIBRAGE — {n} point(s) sur zone 1  |  Clic droit ou Entrée pour valider  |  +clics = meilleur fit"
            self._hint_lbl.config(text=text, fg="#ffcc00")
            return

        mode = self._mode_var.get()
        hints = {
            "add": "Clic gauche → ajouter un impact  |  Molette → zoom",
            "delete": "Clic sur un impact → supprimer  |  Molette → zoom",
            "move": "Glisser un impact → déplacer  |  Molette → zoom",
        }
        self._hint_lbl.config(text=hints.get(mode, ""))

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_resize(self, _event=None):
        self._fit_to_canvas()
        self._redraw()

    def _on_mode_change(self):
        self._selected_idx = None
        self._redraw()

    def _impact_at_canvas(self, cx: float, cy: float) -> int | None:
        """Return index of impact near canvas position, or None."""
        best_idx, best_d = None, IMPACT_RADIUS_SCREEN * 2.5
        for idx, (ix, iy) in enumerate(self._impacts):
            sx, sy = self._orig_to_canvas(ix, iy)
            d = math.hypot(cx - sx, cy - sy)
            if d < best_d:
                best_d, best_idx = d, idx
        return best_idx

    def _on_click(self, event):
        mode = self._mode_var.get()
        cx, cy = event.x, event.y

        # --- Perspective correction intercepts all other modes ---
        if self._persp_step is not None:
            self._handle_persp_click(cx, cy)
            return

        # --- Manual calibration intercepts all other modes ---
        if self._manual_calib_step is not None:
            ox, oy = self._canvas_to_orig(cx, cy)
            self._handle_manual_calib_click(ox, oy)
            return

        if mode == "add":
            ox, oy = self._canvas_to_orig(cx, cy)
            # Only accept clicks within the image bounds
            if self._pil_orig:
                iw, ih = self._pil_orig.size
                if 0 <= ox <= iw and 0 <= oy <= ih:
                    self._impacts.append((ox, oy))
                    self._redraw()
                    self._update_stats()

        elif mode == "delete":
            idx = self._impact_at_canvas(cx, cy)
            if idx is not None:
                self._impacts.pop(idx)
                self._selected_idx = None
                self._redraw()
                self._update_stats()

        elif mode == "move":
            idx = self._impact_at_canvas(cx, cy)
            self._selected_idx = idx
            if idx is not None:
                self._drag_start = (cx, cy)
            self._redraw()

    def _on_drag(self, event):
        if self._mode_var.get() != "move":
            return
        if self._selected_idx is None or self._drag_start is None:
            return
        ox, oy = self._canvas_to_orig(event.x, event.y)
        if self._pil_orig:
            iw, ih = self._pil_orig.size
            ox = max(0, min(iw, ox))
            oy = max(0, min(ih, oy))
        self._impacts[self._selected_idx] = (ox, oy)
        self._redraw()
        self._update_stats()

    def _on_release(self, _event):
        self._drag_start = None

    def _on_mouse_move(self, event):
        # Draw hollow ring cursor during perspective corner selection
        if self._persp_step is not None:
            self._draw_persp_cursor(event.x, event.y)

        # Draw precision reticle during zone-1 calibration
        if self._manual_calib_step is not None:
            self._draw_calib_cursor(event.x, event.y)

        if not self._is_calibrated():
            return
        ox, oy = self._canvas_to_orig(event.x, event.y)
        d_mm = self._orig_dist_mm(ox, oy)
        if d_mm is None:
            return
        score = self._score_at_orig(ox, oy)
        cx, cy = self._center_orig
        dx = (ox - cx) * self._mpp_x
        dy = (oy - cy) * self._mpp_y
        self._cursor_var.set(f"Bague : {score}\n" f"Distance : {d_mm:.1f} mm\n" f"Δx={dx:+.1f}  Δy={dy:+.1f} mm")

    def _on_scroll(self, event):
        """Zoom in/out centred on cursor."""
        # Determine scroll direction
        if hasattr(event, "delta") and event.delta != 0:
            factor = 1.1 if event.delta > 0 else 1 / 1.1
        elif event.num == 4:
            factor = 1.1
        elif event.num == 5:
            factor = 1 / 1.1
        else:
            return

        # Zoom, keeping cursor position fixed in image space
        ox_before, oy_before = self._canvas_to_orig(event.x, event.y)
        self._scale *= factor
        self._scale = max(0.1, min(10.0, self._scale))

        # Adjust offset so the image point under cursor stays under cursor
        offx = event.x - ox_before * self._scale
        offy = event.y - oy_before * self._scale
        self._offset = (offx, offy)
        self._redraw()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def _update_stats(self):
        n = len(self._impacts)
        self._counter_var.set(str(n))

        if n == 0:
            for v in self._svars.values():
                v.set("—")
            for v in self._ring_vars.values():
                v.set("—")
            for v in self._nstat_vars.values():
                v.set("—")
            for store in (
                self._disp_vars,
                self._group_vars,
                self._bias_vars,
                self._cep_group_vars,
                self._cep_poi_vars,
                self._ellipse_vars,
                self._consistency_vars,
            ):
                for v in store.values():
                    v.set("—")
            return

        scores = [self._score_at_orig(x, y) for x, y in self._impacts]
        total = sum(scores)
        avg = total / n
        std = float(np.std(scores))

        cx, cy = self._center_orig if self._center_orig else (0.0, 0.0)
        mpp_x = self._mpp_x or 1.0
        mpp_y = self._mpp_y or 1.0

        dxs = np.array([(x - cx) * mpp_x for x, y in self._impacts], dtype=float)
        dys = np.array([(y - cy) * mpp_y for x, y in self._impacts], dtype=float)
        dists = list(np.sqrt(dxs**2 + dys**2))
        pts = np.column_stack((dxs, dys))

        mean_dx = float(np.mean(dxs))
        mean_dy = float(np.mean(dys))

        # Radial distances from the GROUP BARYCENTRE: internal dispersion,
        # regardless of where the group is centred on the target. This is
        # what the "DISPERSION" section below actually describes.
        centered = np.sqrt((pts[:, 0] - mean_dx) ** 2 + (pts[:, 1] - mean_dy) ** 2)
        mean_r_grp = float(np.mean(centered))
        std_r_grp = float(np.std(centered))
        # np.std computes deviation around the array's own mean, so this is
        # already the per-axis dispersion around the group barycentre.
        std_dx_grp = float(np.std(dxs))
        std_dy_grp = float(np.std(dys))

        # Radial distances from the POINT OF AIM (target centre): `dists`
        # already holds this — it also captures any systematic bias, so it
        # measures overall precision rather than pure group dispersion.
        mean_dist_poi = float(np.mean(dists))
        std_dist_poi = float(np.std(dists))

        bias_x, bias_y = mean_dx, mean_dy

        max_pair = 0.0
        min_x = min(x for x, y in self._impacts)
        max_x = max(x for x, y in self._impacts)
        min_y = min(y for x, y in self._impacts)
        max_y = max(y for x, y in self._impacts)

        for i in range(n):
            x1, y1 = self._impacts[i]
            for j in range(i + 1, n):
                x2, y2 = self._impacts[j]
                d = math.hypot((x2 - x1) * mpp_x, (y2 - y1) * mpp_y)
                if d > max_pair:
                    max_pair = d

        box_w = (max_x - min_x) * mpp_x
        box_h = (max_y - min_y) * mpp_y

        mec_cx, mec_cy, mec_r = minimum_enclosing_circle(pts) if n >= 2 else (0.0, 0.0, 0.0)
        mec_diam = mec_r * 2.0

        self._svars["total"].set(str(total))
        self._svars["avg"].set(f"{avg:.2f}")
        self._svars["best"].set(str(max(scores)))
        self._svars["worst"].set(str(min(scores)))
        self._svars["std"].set(f"{std:.2f}")
        self._svars["pct_max"].set(f"{(total / (n * 10) * 100):.1f} %")

        self._bias_vars["dx"].set(f"{bias_x:+.1f} mm")
        self._bias_vars["dy"].set(f"{bias_y:+.1f} mm")

        self._disp_vars["mean_r"].set(f"{mean_r_grp:.1f} mm")
        self._disp_vars["std_r"].set(f"{std_r_grp:.1f} mm")
        self._disp_vars["std_x"].set(f"{std_dx_grp:.1f} mm")
        self._disp_vars["std_y"].set(f"{std_dy_grp:.1f} mm")

        self._group_vars["max_pair"].set(f"{max_pair:.1f} mm")
        self._group_vars["mec_diam"].set(f"{mec_diam:.1f} mm")

        counts: dict[int, int] = {}
        for s in scores:
            counts[s] = counts.get(s, 0) + 1

        for ring, var in self._ring_vars.items():
            c = counts.get(ring, 0)
            if c:
                var.set(f"{c} (+{ring * c})")
            else:
                var.set("—")

        if n >= 1:
            cep50_group = cep_from_distances(centered, 50)
            cep90_group = cep_from_distances(centered, 90)
            self._cep_group_vars["cep50"].set(f"{cep50_group:.1f} mm")
            self._cep_group_vars["cep90"].set(f"{cep90_group:.1f} mm")

            # Radial distances from the POINT OF AIM (target centre): `dists`
            # already holds this — it also captures any systematic bias.
            poi_dists = np.array(dists, dtype=float)
            cep50_poi = cep_from_distances(poi_dists, 50)
            cep90_poi = cep_from_distances(poi_dists, 90)
            self._cep_poi_vars["cep50"].set(f"{cep50_poi:.1f} mm")
            self._cep_poi_vars["cep90"].set(f"{cep90_poi:.1f} mm")
            self._cep_poi_vars["mean_r"].set(f"{mean_dist_poi:.1f} mm")
            self._cep_poi_vars["std_r"].set(f"{std_dist_poi:.1f} mm")
        else:
            for v in self._cep_group_vars.values():
                v.set("—")
            for v in self._cep_poi_vars.values():
                v.set("—")

        # --- N-dependent reliability indicators ---
        rel = compute_reliability_stats(scores, centered)
        self._nstat_vars["n_tirs"].set(str(rel["n"]))
        self._nstat_vars["score_eq10"].set(f"{rel['score_eq10']:.1f}" if rel["score_eq10"] is not None else "—")
        if rel["mean_ci95"] is not None:
            lo, hi = rel["mean_ci95"]
            self._nstat_vars["mean_ci"].set(f"[{lo:.2f} ; {hi:.2f}]")
        else:
            self._nstat_vars["mean_ci"].set("—")
        self._nstat_vars["flyers"].set(f"{rel['n_flyers']} / {n}")
        if rel["flyer_rate"] is not None:
            self._nstat_vars["flyer_rate"].set(f"{rel['flyer_rate'] * 100:.1f} %")
        else:
            self._nstat_vars["flyer_rate"].set("—")
        if rel["flyer_rate_ci95"] is not None:
            lo, hi = rel["flyer_rate_ci95"]
            self._nstat_vars["flyer_ci"].set(f"[{lo * 100:.1f} ; {hi * 100:.1f}] %")
        else:
            self._nstat_vars["flyer_ci"].set("—")
        if rel["flyer_risk_n"] is not None:
            self._nstat_vars["flyer_risk"].set(f"{rel['flyer_risk_n'] * 100:.1f} %")
        else:
            self._nstat_vars["flyer_risk"].set("—")
        if rel["mean_shots_before_flyer"] is not None:
            self._nstat_vars["shots_bf"].set(f"{rel['mean_shots_before_flyer']:.1f}")
        else:
            self._nstat_vars["shots_bf"].set("∞" if rel["n_flyers"] == 0 else "—")

        if n >= 2:
            cov = np.cov(pts.T)
            eigvals, eigvecs = np.linalg.eigh(cov)
            order = np.argsort(eigvals)[::-1]
            eigvals = eigvals[order]
            eigvecs = eigvecs[:, order]
            a = float(2.0 * np.sqrt(max(eigvals[0], 0.0)))
            b = float(2.0 * np.sqrt(max(eigvals[1], 0.0)))
            aspect = (a / b) if b > 0 else None
            # Angle relative to north (up = 0°), clockwise, so east = 90°
            # — same convention as the on-canvas label.
            angle = float(np.degrees(np.arctan2(eigvecs[0, 0], -eigvecs[1, 0]))) % 180
            self._ellipse_vars["major"].set(f"{a:.1f} mm")
            self._ellipse_vars["minor"].set(f"{b:.1f} mm")
            self._ellipse_vars["aspect"].set(f"{aspect:.2f}" if aspect is not None else "—")
            self._ellipse_vars["angle"].set(f"{angle:.1f}°")
        else:
            for v in self._ellipse_vars.values():
                v.set("—")

        # Coefficient of variation of the group radius (dimensionless):
        # lower means shots land consistently at the same distance from the
        # group centre, regardless of the group's absolute size.
        cv = (std_r_grp / mean_r_grp) if mean_r_grp > 0 else 0.0
        self._consistency_vars["cv"].set(f"{cv:.2f}")

    # ------------------------------------------------------------------
    # Undo / clear
    # ------------------------------------------------------------------

    def _undo(self):
        if self._impacts:
            self._impacts.pop()
            if self._selected_idx is not None:
                self._selected_idx = min(self._selected_idx, len(self._impacts) - 1)
                if self._selected_idx < 0:
                    self._selected_idx = None
            self._redraw()
            self._update_stats()

    def _clear_all(self):
        if self._impacts and messagebox.askyesno("Effacer", "Supprimer tous les impacts ?"):
            self._impacts.clear()
            self._selected_idx = None
            self._redraw()
            self._update_stats()

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def _import_json(self):
        """Resume a session from a previously exported JSON file.

        The JSON must contain a 'calibration' block and an 'impacts' list.
        If the referenced image is available next to the JSON (or the path
        stored in metadata is still valid), it is reloaded automatically;
        otherwise the user is prompted to locate it manually.
        """
        json_path = filedialog.askopenfilename(
            title="Reprendre une session (JSON)",
            filetypes=[("JSON", "*.json"), ("Tous", "*.*")],
        )
        if not json_path:
            return
        self._load_session_from_json(json_path)

    def _load_session_from_json(self, json_path: str):
        """Actually load a session from a known JSON path (shared by the
        'Reprendre cible' file dialog and by double-clicking a row in the
        History window)."""
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de lire le fichier JSON :\n{e}")
            return

        # --- Validate required keys ---
        if "impacts" not in data or "calibration" not in data:
            messagebox.showerror("Erreur", "Fichier JSON invalide : clés 'impacts' et 'calibration' requises.")
            return

        calib = data["calibration"]
        if "center_px" not in calib or ("mm_per_px" not in calib and ("mpp_x" not in calib or "mpp_y" not in calib)):
            messagebox.showerror("Erreur", "Bloc 'calibration' invalide " "(center_px / mpp_x / mpp_y manquants).")
            return

        # --- Try to locate the image to display ---
        # Priority 1: rectified image saved alongside the JSON (_rect.png).
        #   This is the post-warp, post-calib image whose pixel coordinates
        #   match the stored calibration exactly — no need to redo anything.
        # Priority 2: original source image (name stored in metadata).
        #   Usable as a display background only; calibration still applies.
        image_loaded = False
        image_name = data.get("metadata", {}).get("image", "")
        image_rect_name = data.get("metadata", {}).get("image_rectified", "")
        json_dir = os.path.dirname(json_path)

        # Build candidate list: rectified variants first, then originals
        candidates = []
        if image_rect_name:
            candidates.append(os.path.join(json_dir, image_rect_name))
        if image_name:
            candidates.append(os.path.join(json_dir, image_name))
            candidates.append(image_name)  # absolute path as stored

        for candidate in candidates:
            if os.path.isfile(candidate):
                img = cv2.imread(candidate)
                if img is not None:
                    self._img_orig = img
                    self._pil_orig = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                    self._image_stem = os.path.splitext(os.path.basename(candidate))[0]
                    self._path_lbl.config(text=os.path.basename(candidate))
                    image_loaded = True
                    break

        if not image_loaded:
            # Ask user to locate the image manually
            msg = "Image rectifiée introuvable"
            if image_rect_name:
                msg += f" ({image_rect_name})"
            msg += ".\nVoulez-vous localiser l'image manuellement ?\n\n" "(Idéalement fournir le fichier _rect.png — sinon l'image originale.)"
            if messagebox.askyesno("Image manquante", msg):
                manual = filedialog.askopenfilename(
                    title="Localiser l'image de la cible",
                    filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"), ("Tous", "*.*")],
                )
                if manual:
                    img = cv2.imread(manual)
                    if img is not None:
                        self._img_orig = img
                        self._pil_orig = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                        self._image_stem = os.path.splitext(os.path.basename(manual))[0]
                        self._path_lbl.config(text=os.path.basename(manual))
                        image_loaded = True

        if not image_loaded:
            messagebox.showwarning("Session partielle", "Session chargée sans image de fond.\n" "Les impacts et la calibration sont restaurés.")

        # --- Restore calibration ---
        cx, cy = calib["center_px"]
        # Support both old (mm_per_px) and new (mpp_x / mpp_y) JSON formats.
        if "mpp_x" in calib and "mpp_y" in calib:
            mpp_x = float(calib["mpp_x"])
            mpp_y = float(calib["mpp_y"])
        else:
            mpp_x = mpp_y = float(calib.get("mm_per_px", 1.0))
        self._set_calib(float(cx), float(cy), mpp_x, mpp_y, "restauré depuis JSON")

        # --- Restore impacts from pixel coordinates ---
        self._impacts.clear()
        self._selected_idx = None
        skipped = 0
        for entry in data["impacts"]:
            try:
                x = float(entry["x_px"])
                y = float(entry["y_px"])
                self._impacts.append((x, y))
            except (KeyError, ValueError, TypeError):
                skipped += 1

        # Update stem from JSON filename if no image was found
        if not image_loaded:
            self._image_stem = os.path.splitext(os.path.basename(json_path))[0]
            # Strip trailing "_data" suffix if present
            if self._image_stem.endswith("_data"):
                self._image_stem = self._image_stem[:-5]

        # --- Restore caliber (munition), if it was recorded on export ---
        caliber = data.get("metadata", {}).get("caliber")
        if caliber in CALIBERS:
            self._caliber_var.set(caliber)

        self._fit_to_canvas()
        self._redraw()
        self._update_stats()

        n = len(self._impacts)
        msg = f"Session restaurée : {n} impact(s).\nCalibration conservée (centre + échelles X/Y)."
        if skipped:
            msg += f"\n({skipped} entrée(s) ignorée(s) — données manquantes)"
        messagebox.showinfo("Session reprise", msg)

    # ------------------------------------------------------------------
    # Circle fit helper (algebraic least-squares, Coope 1993)
    # ------------------------------------------------------------------

    @staticmethod
    def _fit_circle_lsq(pts: list[tuple[float, float]]) -> tuple[float, float, float]:
        """Fit a circle to 3 or more 2-D points using algebraic least squares.

        Returns (cx, cy, radius_px).  Works exactly for 3 points and gives the
        best L2 fit for N > 3.

        Method: rewrite (x-cx)² + (y-cy)² = r² as the linear system
            2·cx·xi + 2·cy·yi + (r²-cx²-cy²) = xi² + yi²
        and solve for [cx, cy, c] where c = r²-cx²-cy².
        """
        A = np.array([[2 * x, 2 * y, 1.0] for x, y in pts], dtype=float)
        b = np.array([x * x + y * y for x, y in pts], dtype=float)
        result, *_ = np.linalg.lstsq(A, b, rcond=None)
        cx, cy, c = result
        r = math.sqrt(max(0.0, c + cx * cx + cy * cy))
        return float(cx), float(cy), float(r)

    # ------------------------------------------------------------------
    # Manual calibration: 3+ clicks on ring-1 outer edge
    # ------------------------------------------------------------------

    def _start_manual_calib(self):
        """Start the N-point manual calibration sequence (N ≥ 3).

        The user clicks 3 or more points on the outer edge of ring 1 (r = 250 mm).
        After each click a preview circle is drawn.  The calibration is confirmed
        with a right-click (or automatically when exactly 3 points have been placed
        and the user presses Enter).

        The target centre and mm/px scale are both derived from the circle fit —
        the user never has to click the centre directly.
        """
        if self._pil_orig is None:
            messagebox.showinfo("Calibrage manuel", "Chargez d'abord une image.")
            return
        self._manual_calib_step = "ring1_pts"
        self._manual_calib_pts = []
        self._hint_lbl.config(text="CALIBRAGE — Clics sur le bord de la ZONE 1 (≥ 3)  |  " "Clic droit ou Entrée pour valider", fg="#ffcc00")
        # Hide system cursor — we draw our own precision reticle
        self._canvas.config(cursor="none")
        # Bind right-click and Enter key to validation
        self._canvas.bind("<Button-3>", lambda _e: self._finish_manual_calib())
        self.bind("<Return>", lambda _e: self._finish_manual_calib())

    def _handle_manual_calib_click(self, ox: float, oy: float):
        """Accumulate a ring-1 edge click and refresh the preview."""
        if self._manual_calib_step != "ring1_pts":
            return

        self._manual_calib_pts.append((ox, oy))
        n = len(self._manual_calib_pts)

        # Redraw base image, then overlay collected points and current circle fit
        self._redraw()
        c = self._canvas

        # Draw each collected point as a small yellow cross
        for px, py in self._manual_calib_pts:
            sx, sy = self._orig_to_canvas(px, py)
            arm = 7
            c.create_line(sx - arm, sy, sx + arm, sy, fill="#ffcc00", width=2, tags="calib_hint")
            c.create_line(sx, sy - arm, sx, sy + arm, fill="#ffcc00", width=2, tags="calib_hint")

        # Draw preview ellipse once we have ≥ 3 points
        if n >= 3:
            # Reuse the same ellipse fit logic as _finish_manual_calib
            cx_fit, cy_fit, _ = self._fit_circle_lsq(self._manual_calib_pts)
            pts_arr = np.array(self._manual_calib_pts, dtype=float)
            u = (pts_arr[:, 0] - cx_fit) ** 2
            v = (pts_arr[:, 1] - cy_fit) ** 2
            A_p = np.column_stack([u, v])
            b_p = np.ones(n)
            res, *_ = np.linalg.lstsq(A_p, b_p, rcond=None)
            a_c, b_c = res
            if a_c > 0 and b_c > 0:
                rx_fit = 1.0 / math.sqrt(a_c)
                ry_fit = 1.0 / math.sqrt(b_c)
            else:
                rx_fit = ry_fit = float(np.mean(np.sqrt(u + v)))
            scx, scy = self._orig_to_canvas(cx_fit, cy_fit)
            rx_scr = rx_fit * self._scale
            ry_scr = ry_fit * self._scale
            c.create_oval(scx - rx_scr, scy - ry_scr, scx + rx_scr, scy + ry_scr, outline="#ffcc00", width=2, dash=(6, 4), tags="calib_hint")
            # Preview centre crosshair
            arm = 10
            c.create_line(scx - arm, scy, scx + arm, scy, fill="#ffcc00", width=2, tags="calib_hint")
            c.create_line(scx, scy - arm, scx, scy + arm, fill="#ffcc00", width=2, tags="calib_hint")

        self._hint_lbl.config(text=f"CALIBRAGE — {n} point(s) sur zone 1  |  " "Clic droit ou Entrée pour valider  |  +clics = meilleur fit", fg="#ffcc00")

    def _finish_manual_calib(self):
        """Validate the ellipse fit and apply the calibration.

        We fit an axis-aligned ellipse to the clicked ring-1 edge points.
        This handles the common case where the rectified image is slightly
        stretched vertically or horizontally relative to the physical target.

        Method: first fit a circle (Coope LSQ) to get the centre, then
        derive independent rx / ry by computing the RMS horizontal and vertical
        residuals of all points around that centre.  This is robust and avoids
        the non-linear ellipse fitting problem.
        """
        # Unbind temporary shortcuts
        self._canvas.unbind("<Button-3>")
        self.unbind("<Return>")

        pts = self._manual_calib_pts
        n_pts = len(pts)
        if n_pts < 3:
            messagebox.showwarning("Calibrage manuel", f"Il faut au moins 3 points (actuellement {n_pts}).\n" "Recommencez.")
            self._start_manual_calib()
            return

        # Step 1: least-squares circle fit → best centre estimate
        cx, cy, r_avg = self._fit_circle_lsq(pts)

        if r_avg < 10:
            messagebox.showwarning("Calibrage manuel", "Rayon calculé trop petit — points trop groupés ? Recommencez.")
            self._start_manual_calib()
            return

        # Step 2: derive per-axis radii.
        # For each clicked point P = (px, py) on the true ellipse with semi-axes
        # (rx, ry), we know: (px-cx)²/rx² + (py-cy)²/ry² = 1.
        # We do a 2-variable linear least squares on the substitution
        # u = (px-cx)², v = (py-cy)²  →  u/rx² + v/ry² = 1
        # i.e. [u  v] · [1/rx²  1/ry²]ᵀ = 1   → solve for [a, b] = [1/rx², 1/ry²].
        pts_arr = np.array(pts, dtype=float)
        u = (pts_arr[:, 0] - cx) ** 2
        v = (pts_arr[:, 1] - cy) ** 2
        A = np.column_stack([u, v])
        b = np.ones(n_pts)
        result, *_ = np.linalg.lstsq(A, b, rcond=None)
        a_coef, b_coef = result
        # Guard against degenerate (near-zero or negative) coefficients
        if a_coef <= 0 or b_coef <= 0:
            # Fall back to isotropic circle
            rx_px = ry_px = r_avg
        else:
            rx_px = 1.0 / math.sqrt(a_coef)  # horizontal semi-axis in px
            ry_px = 1.0 / math.sqrt(b_coef)  # vertical   semi-axis in px

        # ring-1 outer radius = 250 mm
        mpp_x = 250.0 / rx_px
        mpp_y = 250.0 / ry_px
        n_save = n_pts
        self._manual_calib_step = None
        self._manual_calib_pts = []

        self._set_calib(cx, cy, mpp_x, mpp_y, f"manuel — {n_save} pts — " f"rx={rx_px:.0f} ry={ry_px:.0f} px")
        self._hint_lbl.config(text="Clic gauche → ajouter un impact  |  Molette → zoom", fg="#ffffff")
        self._canvas.delete("calib_cursor")
        self._canvas.config(cursor="crosshair")
        self._fit_to_canvas()
        self._redraw()
        self._update_stats()

    # ------------------------------------------------------------------
    # Perspective correction (manual 4-corner click)
    # ------------------------------------------------------------------

    CORNER_LABELS = [
        "coin HAUT-GAUCHE",
        "coin HAUT-DROIT",
        "coin BAS-DROIT",
        "coin BAS-GAUCHE",
    ]

    def _start_persp_click(self):
        """Begin the 4-corner manual perspective correction sequence."""
        if self._pil_orig is None:
            messagebox.showinfo("Correction perspective", "Chargez d'abord une image.")
            return

        # Ask for the physical card size first; cancelling aborts the calibration.
        dlg = CardSizeDialog(self, self._card_size_mm)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        self._card_size_mm = dlg.result

        self._persp_step = 0
        self._persp_corners = []
        self._update_persp_hint()
        # Hide system cursor — we'll draw our own ring
        self._canvas.config(cursor="none")

    def _update_persp_hint(self):
        if self._persp_step is None:
            return
        label = self.CORNER_LABELS[self._persp_step]
        self._hint_lbl.config(text=f"PERSPECTIVE — Clic {self._persp_step+1}/4 : {label}", fg="#ff88ff")

    def _handle_persp_click(self, cx: float, cy: float):
        """Handle a canvas click during the 4-corner perspective sequence.
        cx, cy are canvas pixel coordinates (not image-space).
        """
        self._persp_corners.append((cx, cy))
        self._persp_step += 1

        # Draw a small permanent marker on the canvas at each collected corner
        r = 6
        self._canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#ff88ff", width=2, tags="persp_marker")
        self._canvas.create_line(cx - 10, cy, cx + 10, cy, fill="#ff88ff", width=1, tags="persp_marker")
        self._canvas.create_line(cx, cy - 10, cx, cy + 10, fill="#ff88ff", width=1, tags="persp_marker")

        if self._persp_step < 4:
            self._update_persp_hint()
            return

        # All 4 corners collected — apply perspective warp
        self._persp_step = None
        self._canvas.config(cursor="crosshair")
        self._hint_lbl.config(text="Clic gauche → ajouter un impact  |  Molette → zoom", fg="#ffffff")
        self._canvas.delete("persp_marker")
        self._canvas.delete("persp_cursor")

        # Convert canvas coordinates → original image coordinates
        corners_orig = np.array([self._canvas_to_orig(cx, cy) for cx, cy in self._persp_corners], dtype=np.float32)
        # Apply warp to the original image
        # Rectify to a canvas matching the chosen card size, so mm/px stays
        # identical on both axes.
        warp_w, warp_h = card_canvas_size_px(*self._card_size_mm)
        img_warped = correct_perspective(self._img_orig, corners_orig, warp_w, warp_h)
        self._img_orig = img_warped
        self._pil_orig = Image.fromarray(cv2.cvtColor(img_warped, cv2.COLOR_BGR2RGB))
        self._impacts.clear()
        self._selected_idx = None
        self._calibrate()
        self._fit_to_canvas()
        self._redraw()
        self._update_stats()
        self._hint_lbl.config(text="Perspective corrigée manuellement  |  Clic gauche → ajouter un impact", fg="#55ff55")
        self.after(3000, lambda: self._hint_lbl.config(text="Clic gauche → ajouter un impact  |  Molette → zoom", fg="#ffffff"))

    def _draw_persp_cursor(self, cx: int, cy: int):
        """Draw a hollow ring cursor on the canvas (replaces system cursor)."""
        self._canvas.delete("persp_cursor")
        c = self._canvas
        r = 20
        gap = 5
        color = "#ff88ff"

        c.create_line(cx - r, cy, cx - gap, cy, fill=color, width=2, tag="persp_cursor")
        c.create_line(cx + gap, cy, cx + r, cy, fill=color, width=2, tag="persp_cursor")
        c.create_line(cx, cy - r, cx, cy - gap, fill=color, width=2, tag="persp_cursor")
        c.create_line(cx, cy + gap, cx, cy + r, fill=color, width=2, tag="persp_cursor")
        c.create_oval(cx - 1, cy - 1, cx + 1, cy + 1, fill=color, outline="", tag="persp_cursor")

    def _draw_calib_cursor(self, cx: int, cy: int):
        """Draw a CAD-style precision cursor for zone-1 calibration clicks:
        hairlines spanning the whole canvas (1 px wide, so they never hide the
        ring edge being targeted) plus a small square pick box at the
        intersection."""
        self._canvas.delete("calib_cursor")
        c = self._canvas
        w = c.winfo_width()
        h = c.winfo_height()
        box = 9  # half-size of the pick box (px); the hairlines stop at its edge
        color = "#00e5ff"  # hairlines + pick box
        halo = "#000000"  # dark underlay so the hairlines stay visible on any background
        tags = ("calib_cursor",)

        # Full-span hairlines (horizontal + vertical): a 3 px dark halo with a
        # 1 px bright line on top, so they read on both light and dark paper.
        # The lines stop at the edge of the pick box, so the area inside the
        # box stays clear and the ring edge being targeted remains visible.
        segments = (
            (0, cy, cx - box, cy),  # left
            (cx + box, cy, w, cy),  # right
            (cx, 0, cx, cy - box),  # top
            (cx, cy + box, cx, h),  # bottom
        )
        for x0, y0, x1, y1 in segments:
            c.create_line(x0, y0, x1, y1, fill=halo, width=3, tags=tags)
            c.create_line(x0, y0, x1, y1, fill=color, width=1, tags=tags)
        # Pick box centred on the exact click point.
        c.create_rectangle(cx - box, cy - box, cx + box, cy + box, outline=halo, width=3, tags=tags)
        c.create_rectangle(cx - box, cy - box, cx + box, cy + box, outline=color, width=1, tags=tags)
        # Make sure nothing drawn earlier (rings, impacts, calibration hints) covers the cursor.
        c.tag_raise("calib_cursor")

    def _export_all(self):
        """Export CSV, JSON and annotated image to the same folder as the source image.
        No file picker — saves immediately with automatic names."""
        if not self._impacts:
            messagebox.showinfo("Export", "Aucun impact à exporter.")
            return

        # Resolve output folder: same directory as source image if we can find it
        img_name = self._path_lbl.cget("text")
        src_dir = ""
        if img_name and img_name not in ("—", ""):
            for search_dir in [
                os.path.expanduser("~/Downloads"),
                os.path.expanduser("~"),
                os.getcwd(),
            ]:
                if os.path.isfile(os.path.join(search_dir, img_name)):
                    src_dir = search_dir
                    break

        if not src_dir:
            src_dir = filedialog.askdirectory(title="Choisir le dossier de sauvegarde")
            if not src_dir:
                return

        stem = self._image_stem
        p_csv = os.path.join(src_dir, f"{stem}_impacts.csv")
        p_json = os.path.join(src_dir, f"{stem}_data.json")
        p_img = os.path.join(src_dir, f"{stem}_annotee.png")

        errors = []
        for label, path, writer in [
            ("CSV", p_csv, self._write_csv),
            ("JSON", p_json, self._write_json),
            ("Image", p_img, self._write_image),
        ]:
            try:
                writer(path)
            except Exception as e:
                errors.append(f"{label} : {e}")

        if errors:
            messagebox.showerror("Export partiel", "\n".join(errors))
        else:
            p_rect = p_json.replace(".json", "_rect.png")
            names = "\n".join(
                [os.path.basename(p_csv), os.path.basename(p_json), os.path.basename(p_rect) + "  ← image rectifiée (session)", os.path.basename(p_img)]
            )
            messagebox.showinfo("Export", f"Sauvegardé dans :\n{src_dir}\n\n{names}")

    def _export_csv(self):
        if not self._impacts:
            messagebox.showinfo("Export", "Aucun impact à exporter.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"{self._image_stem}_impacts.csv",
        )
        if path:
            self._write_csv(path)

    def _write_csv(self, path: str):
        """Write impact data to a CSV file at the given path."""
        cx0, cy0 = self._center_orig or (0, 0)
        mpp_x = self._mpp_x or 1.0
        mpp_y = self._mpp_y or 1.0
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("n,score,dist_mm,dx_mm,dy_mm,x_px,y_px\n")
            for i, (x, y) in enumerate(self._impacts, 1):
                dx = (x - cx0) * mpp_x
                dy = (y - cy0) * mpp_y
                dist = math.hypot(dx, dy)
                s = self._score_at_orig(x, y)
                f.write(f"{i},{s},{dist:.1f},{dx:+.1f},{dy:+.1f},{x:.0f},{y:.0f}\n")

    def _export_json(self):
        """Export all impact data and statistics to a structured JSON file."""
        if not self._impacts:
            messagebox.showinfo("Export", "Aucun impact à exporter.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"{self._image_stem}_data.json",
        )
        if path:
            self._write_json(path)

    def _write_json(self, path: str):
        """Write full session data (impacts + statistics) to a JSON file."""
        import json
        from datetime import datetime

        cx0, cy0 = self._center_orig or (0.0, 0.0)
        mpp_x = self._mpp_x or 1.0
        mpp_y = self._mpp_y or 1.0
        n = len(self._impacts)
        scores = [self._score_at_orig(x, y) for x, y in self._impacts]
        dxs = np.array([(x - cx0) * mpp_x for x, y in self._impacts], dtype=float)
        dys = np.array([(y - cy0) * mpp_y for x, y in self._impacts], dtype=float)
        dists = np.sqrt(dxs**2 + dys**2)
        pts = np.column_stack((dxs, dys))

        impacts_list = []
        for i, ((x, y), s) in enumerate(zip(self._impacts, scores), 1):
            dx = (x - cx0) * mpp_x
            dy = (y - cy0) * mpp_y
            impacts_list.append(
                {
                    "n": i,
                    "score": s,
                    "dist_mm": round(math.hypot(dx, dy), 2),
                    "dx_mm": round(dx, 2),
                    "dy_mm": round(dy, 2),
                    "x_px": round(x, 1),
                    "y_px": round(y, 1),
                }
            )

        total = sum(scores)
        avg = total / n
        std_s = float(np.std(scores))
        mean_dx = float(np.mean(dxs))
        mean_dy = float(np.mean(dys))
        std_r = float(np.std(dists))
        mean_r = float(np.mean(dists))
        centered = np.sqrt((dxs - mean_dx) ** 2 + (dys - mean_dy) ** 2)
        # Groupement = centred on the group barycentre (internal dispersion).
        cep50_group = cep_from_distances(centered, 50)
        cep90_group = cep_from_distances(centered, 90)
        # Point visé = centred on the target centre / point of aim (also
        # reflects systematic bias, not just dispersion).
        cep50_poi = cep_from_distances(dists, 50)
        cep90_poi = cep_from_distances(dists, 90)
        mec_cx, mec_cy, mec_r = minimum_enclosing_circle(pts)

        max_pair = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                d = math.hypot(dxs[i] - dxs[j], dys[i] - dys[j])
                if d > max_pair:
                    max_pair = d

        ring_counts = {}
        for s in scores:
            ring_counts[str(s)] = ring_counts.get(str(s), 0) + 1

        cv = round(std_s / avg * 100, 1) if avg > 0 else None
        stats = {
            "total_score": total,
            "average": round(avg, 3),
            "std_score": round(std_s, 3),
            "cv_percent": cv,
            "pct_perfect": round(total / (n * 10) * 100, 1),
            "best": max(scores),
            "worst": min(scores),
            "above_threshold": {str(t): int(sum(1 for s in scores if s >= t)) for t in (8, 9, 10)},
            "mean_radius_mm": round(mean_r, 2),
            "std_radius_mm": round(std_r, 2),
            # Kept for backward compatibility with older history exports:
            # these are the "groupement" values (centred on the barycentre).
            "cep50_mm": round(cep50_group, 2),
            "cep90_mm": round(cep90_group, 2),
            "cep50_group_mm": round(cep50_group, 2),
            "cep90_group_mm": round(cep90_group, 2),
            "cep50_poi_mm": round(cep50_poi, 2),
            "cep90_poi_mm": round(cep90_poi, 2),
            "bias_dx_mm": round(mean_dx, 2),
            "bias_dy_mm": round(mean_dy, 2),
            "mec_cx_mm": round(mec_cx, 2),
            "mec_cy_mm": round(mec_cy, 2),
            "mec_radius_mm": round(mec_r, 2),
            "mec_diameter_mm": round(mec_r * 2, 2),
            "max_spread_mm": round(max_pair, 2),
            "bounding_box_mm": {
                "w": round(float(np.max(dxs) - np.min(dxs)), 2),
                "h": round(float(np.max(dys) - np.min(dys)), 2),
            },
            "ring_distribution": ring_counts,
        }
        if n >= 2:
            cov = np.cov(pts.T)
            eigvals, eigvecs = np.linalg.eigh(cov)
            order = np.argsort(eigvals)[::-1]
            eigvals = eigvals[order]
            eigvecs = eigvecs[:, order]
            a = float(2.0 * np.sqrt(max(eigvals[0], 0.0)))
            b = float(2.0 * np.sqrt(max(eigvals[1], 0.0)))
            # Angle relative to north (up = 0°), clockwise, so east = 90°
            # — same convention as the on-canvas label and the stats panel.
            angle = float(np.degrees(np.arctan2(eigvecs[0, 0], -eigvecs[1, 0]))) % 180
            stats["ellipse"] = {
                "major_2sigma_mm": round(a, 2),
                "minor_2sigma_mm": round(b, 2),
                "angle_deg": round(angle, 1),
                "aspect_ratio": round(a / b, 3) if b > 0 else None,
            }

        rel = compute_reliability_stats(scores, centered)
        stats["reliability"] = {
            "n": rel["n"],
            "score_eq10": round(rel["score_eq10"], 2) if rel["score_eq10"] is not None else None,
            "mean_ci95": [round(v, 3) for v in rel["mean_ci95"]] if rel["mean_ci95"] else None,
            "n_flyers": rel["n_flyers"],
            "flyer_rate_percent": round(rel["flyer_rate"] * 100, 1) if rel["flyer_rate"] is not None else None,
            "flyer_rate_ci95_percent": [round(v * 100, 1) for v in rel["flyer_rate_ci95"]] if rel["flyer_rate_ci95"] else None,
            "flyer_risk_n_percent": round(rel["flyer_risk_n"] * 100, 1) if rel["flyer_risk_n"] is not None else None,
            "mean_shots_before_flyer": round(rel["mean_shots_before_flyer"], 1) if rel["mean_shots_before_flyer"] is not None else None,
        }

        payload = {
            "metadata": {
                "image": self._path_lbl.cget("text"),
                "image_rectified": os.path.basename(path).replace(".json", "_rect.png"),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "time": datetime.now().strftime("%H:%M:%S"),
                "n_impacts": n,
                "caliber": self._caliber_var.get(),
            },
            "calibration": {
                "center_px": [round(cx0, 1), round(cy0, 1)],
                "mpp_x": round(mpp_x, 6),
                "mpp_y": round(mpp_y, 6),
            },
            "impacts": impacts_list,
            "statistics": stats,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        # Save the rectified (post-warp, post-calib) image alongside the JSON.
        # This allows _import_json to restore the exact image state without
        # having to redo perspective correction and zone-1 calibration.
        rect_path = path.replace(".json", "_rect.png")
        if self._pil_orig is not None:
            try:
                self._pil_orig.convert("RGB").save(rect_path)
            except Exception:
                pass  # non-fatal — session can still be loaded without it

    def _export_image(self):
        """Export the target image with all impacts and overlays drawn via PIL."""
        if self._pil_orig is None:
            messagebox.showinfo("Export", "Aucune image chargée.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")],
            initialfile=f"{self._image_stem}_annotee.png",
        )
        if path:
            self._write_image(path)

    def _write_image(self, path: str):
        """Render and save the annotated target image to the given path."""
        img = self._pil_orig.copy().convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        cx0, cy0 = self._center_orig or (0.0, 0.0)

        # Ring ellipses (independent radii per axis when mpp_x ≠ mpp_y)
        wimg_mpp_x = self._mpp_x or 1.0
        wimg_mpp_y = self._mpp_y or 1.0
        for ring, r_mm in RINGS_MM.items():
            rx_px = r_mm / wimg_mpp_x
            ry_px = r_mm / wimg_mpp_y
            color_hex = RING_COLORS.get(ring, "#888888")
            r_c = int(color_hex[1:3], 16)
            g_c = int(color_hex[3:5], 16)
            b_c = int(color_hex[5:7], 16)
            draw.ellipse([cx0 - rx_px, cy0 - ry_px, cx0 + rx_px, cy0 + ry_px], outline=(r_c, g_c, b_c, 180), width=2)

        # Centre crosshair
        arm = 20
        draw.line([cx0 - arm, cy0, cx0 + arm, cy0], fill=(64, 255, 64, 220), width=3)
        draw.line([cx0, cy0 - arm, cx0, cy0 + arm], fill=(64, 255, 64, 220), width=3)

        # Impacts — sized to bullet radius
        n = len(self._impacts)
        scores = [self._score_at_orig(x, y) for x, y in self._impacts]
        bullet_radius_mm = CALIBERS.get(self._caliber_var.get(), 4.5)
        _avg_mpp = ((self._mpp_x or 1.0) + (self._mpp_y or 1.0)) / 2.0
        r_dot = max(8, min(22, int(bullet_radius_mm / _avg_mpp)))
        for x, y in self._impacts:
            draw.ellipse([x - r_dot, y - r_dot, x + r_dot, y + r_dot], fill=(255, 68, 68, 210), outline=(255, 255, 255, 255), width=2)

        # MEC
        if n >= 2:
            _mpp_x_w = self._mpp_x or 1.0
            _mpp_y_w = self._mpp_y or 1.0
            dxs = np.array([(x - cx0) * _mpp_x_w for x, y in self._impacts], dtype=float)
            dys = np.array([(y - cy0) * _mpp_y_w for x, y in self._impacts], dtype=float)
            pts = np.column_stack((dxs, dys))
            mec_cx, mec_cy, mec_r = minimum_enclosing_circle(pts)
            mx = cx0 + mec_cx / _mpp_x_w
            my = cy0 + mec_cy / _mpp_y_w
            mr = mec_r / _avg_mpp
            draw.ellipse([mx - mr, my - mr, mx + mr, my + mr], outline=(0, 238, 68, 220), width=3)
            arm2 = 8
            draw.line([mx - arm2, my, mx + arm2, my], fill=(0, 238, 68, 220), width=2)
            draw.line([mx, my - arm2, mx, my + arm2], fill=(0, 238, 68, 220), width=2)

        # CEP 50 / CEP 90 circles (centred on group barycentre)
        if n >= 1:
            _mpp_x_w = self._mpp_x or 1.0
            _mpp_y_w = self._mpp_y or 1.0
            dxs_c = np.array([(x - cx0) * _mpp_x_w for x, y in self._impacts], dtype=float)
            dys_c = np.array([(y - cy0) * _mpp_y_w for x, y in self._impacts], dtype=float)
            mean_dx = float(np.mean(dxs_c))
            mean_dy = float(np.mean(dys_c))
            centered = np.sqrt((dxs_c - mean_dx) ** 2 + (dys_c - mean_dy) ** 2)
            # Barycentre in image pixels
            bcx = cx0 + mean_dx / _mpp_x_w
            bcy = cy0 + mean_dy / _mpp_y_w

            if self._show_cep50.get():
                cep50_r = cep_from_distances(centered, 50)
                r50_px = cep50_r / _avg_mpp
                draw.ellipse([bcx - r50_px, bcy - r50_px, bcx + r50_px, bcy + r50_px], outline=(0, 207, 255, 220), width=3)

            if self._show_cep90.get() and n >= 2:
                cep90_r = cep_from_distances(centered, 90)
                r90_px = cep90_r / _avg_mpp
                draw.ellipse([bcx - r90_px, bcy - r90_px, bcx + r90_px, bcy + r90_px], outline=(255, 68, 204, 220), width=3)

        img = Image.alpha_composite(img, overlay)

        # Stats panel
        panel_w, panel_h = 340, 200
        margin = 20
        px_pos = img.width - panel_w - margin
        py_pos = img.height - panel_h - margin
        panel = Image.new("RGBA", (panel_w, panel_h), (10, 10, 20, 200))
        pdraw = ImageDraw.Draw(panel)

        try:
            font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 20)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 13)
        except OSError:
            font_big = font_small = ImageFont.load_default()

        total = sum(scores)
        avg = total / n if n > 0 else 0
        _mpp_x_s = self._mpp_x or 1.0
        _mpp_y_s = self._mpp_y or 1.0
        dists = [math.hypot((x - cx0) * _mpp_x_s, (y - cy0) * _mpp_y_s) for x, y in self._impacts]
        mean_r = float(np.mean(dists)) if dists else 0.0
        mean_dx = float(np.mean([(x - cx0) * _mpp_x_s for x, y in self._impacts]))
        mean_dy = float(np.mean([(y - cy0) * _mpp_y_s for x, y in self._impacts]))
        centered = np.sqrt(
            (np.array([(x - cx0) * _mpp_x_s for x, y in self._impacts]) - mean_dx) ** 2
            + (np.array([(y - cy0) * _mpp_y_s for x, y in self._impacts]) - mean_dy) ** 2
        )
        # Panel is small: show the "groupement" CEP50 (internal dispersion),
        # matching the on-canvas circle label "CEP50 (grp)".
        cep50_group = cep_from_distances(centered, 50) if n >= 1 else 0.0

        lines = [
            (f"  {n} impacts — {total} pts  ", font_big, (255, 255, 160)),
            (f"  Moy. {avg:.2f}  |  ↑{max(scores)}  ↓{min(scores)}", font_small, (192, 192, 232)),
            (f"  R.moy {mean_r:.1f} mm  |  CEP50 grp {cep50_group:.1f} mm", font_small, (192, 192, 232)),
        ]
        if n >= 2:
            lines.append((f"  MEC Ø {mec_r * 2:.1f} mm", font_small, (0, 238, 68)))
            lines.append((f"  Biais ΔX {mean_dx:+.1f}  ΔY {mean_dy:+.1f} mm", font_small, (255, 136, 0)))
        counts = {}
        for s in scores:
            counts[s] = counts.get(s, 0) + 1
        lines.append(("  " + "  ".join(f"{k}×{v}" for k, v in sorted(counts.items(), reverse=True)), font_small, (200, 200, 200)))

        y_txt = 12
        for text, font, color in lines:
            pdraw.text((0, y_txt), text, font=font, fill=color)
            y_txt += 30 if font is font_big else 24

        img.paste(panel, (px_pos, py_pos), panel)
        final = img.convert("RGB") if path.lower().endswith((".jpg", ".jpeg")) else img
        final.save(path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    app = TargetApp(initial_path=initial)
    app.mainloop()


if __name__ == "__main__":
    main()
