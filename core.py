"""Cœur de DeskOrg : planification, exécution, journal et annulation."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DOSSIER_APP = Path.home() / ".deskorg"
CONFIG_PATH = DOSSIER_APP / "config.json"
JOURNAL_PATH = DOSSIER_APP / "journal.json"

CONFIG_DEFAUT = {
    "dossier": "~/Desktop",
    "dossier_autres": "Autres",
    "dossier_doublons": "Doublons",
    "regles": {
        "Images": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"],
        "Documents": [".pdf", ".doc", ".docx", ".txt", ".odt", ".md", ".rtf"],
        "Tableurs": [".xls", ".xlsx", ".csv", ".ods"],
        "Présentations": [".ppt", ".pptx", ".odp"],
        "Vidéos": [".mp4", ".mkv", ".avi", ".mov", ".webm"],
        "Audio": [".mp3", ".wav", ".flac", ".m4a", ".ogg"],
        "Archives": [".zip", ".rar", ".7z", ".tar", ".gz"],
        "Code": [".py", ".php", ".js", ".html", ".css", ".json", ".sql"],
        "Installateurs": [".exe", ".msi", ".deb", ".dmg", ".apk"],
    },
    # Extensions jamais déplacées (raccourcis, fichiers système, téléchargements en cours)
    "ignorer": [
        ".lnk", ".url", ".desktop", ".ini",
        ".crdownload", ".part", ".tmp", ".download",
    ],
}


@dataclass
class Deplacement:
    src: Path
    dest: Path
    note: str = ""  # "", "doublon" ou "renommé"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def charger_config(chemin: Path | None = None) -> dict:
    """Config par défaut, surchargée par un fichier JSON si fourni ou présent."""
    config = copy.deepcopy(CONFIG_DEFAUT)
    if chemin is None and CONFIG_PATH.exists():
        chemin = CONFIG_PATH
    if chemin is not None:
        config.update(json.loads(Path(chemin).read_text(encoding="utf-8")))
    return config


def ecrire_config_defaut(chemin: Path = CONFIG_PATH) -> Path:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(CONFIG_DEFAUT, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chemin


# --------------------------------------------------------------------------- #
# Planification
# --------------------------------------------------------------------------- #
def categorie(fichier: Path, config: dict) -> str:
    ext = fichier.suffix.lower()
    for nom, extensions in config["regles"].items():
        if ext in extensions:
            return nom
    return config["dossier_autres"]


def _meme_contenu(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False

    def empreinte(p: Path) -> str:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for bloc in iter(lambda: f.read(1024 * 1024), b""):
                h.update(bloc)
        return h.hexdigest()

    return empreinte(a) == empreinte(b)


def _libre(dest: Path, reserves: set[Path]) -> Path:
    """Renvoie dest, ou 'nom (1).ext', 'nom (2).ext'... s'il est déjà pris."""
    if not dest.exists() and dest not in reserves:
        return dest
    n = 1
    while True:
        candidat = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        if not candidat.exists() and candidat not in reserves:
            return candidat
        n += 1


def planifier(config: dict, dossier: str | Path | None = None) -> list[Deplacement]:
    """Calcule les déplacements à faire, sans toucher aux fichiers."""
    racine = Path(dossier or config["dossier"]).expanduser()
    if not racine.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {racine}")

    ignorer = {e.lower() for e in config["ignorer"]}
    plan: list[Deplacement] = []
    reserves: set[Path] = set()

    for f in sorted(racine.iterdir()):
        if (
            not f.is_file()
            or f.is_symlink()
            or f.name.startswith(".")
            or f.suffix.lower() in ignorer
        ):
            continue

        dest = racine / categorie(f, config) / f.name
        note = ""
        if dest.exists() and _meme_contenu(f, dest):
            dest = racine / config["dossier_doublons"] / f.name
            note = "doublon"

        final = _libre(dest, reserves)
        if final != dest and not note:
            note = "renommé"
        reserves.add(final)
        plan.append(Deplacement(f, final, note))

    return plan


# --------------------------------------------------------------------------- #
# Journal, exécution, annulation
# --------------------------------------------------------------------------- #
def lire_journal(journal: Path = JOURNAL_PATH) -> list[dict]:
    journal = Path(journal)
    if not journal.exists():
        return []
    return json.loads(journal.read_text(encoding="utf-8"))


def _ecrire_journal(journal: Path, data: list[dict]) -> None:
    journal = Path(journal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    tmp = journal.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, journal)  # écriture atomique


def executer(plan: list[Deplacement], journal: Path = JOURNAL_PATH):
    """Déplace les fichiers et note l'opération. Renvoie (nb_faits, erreurs)."""
    faits, erreurs = [], []
    for d in plan:
        try:
            if d.dest.exists():
                raise FileExistsError(f"{d.dest} existe déjà")
            d.dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d.src), str(d.dest))
            faits.append({"src": str(d.src), "dest": str(d.dest)})
        except OSError as e:
            erreurs.append((d, e))

    if faits:
        data = lire_journal(journal)
        data.append(
            {"date": datetime.now().isoformat(timespec="seconds"), "deplacements": faits}
        )
        _ecrire_journal(journal, data)
    return len(faits), erreurs


def annuler(journal: Path = JOURNAL_PATH):
    """Annule la dernière opération. Renvoie (restaurés, ignorés) ou None."""
    data = lire_journal(journal)
    if not data:
        return None

    restaures, ignores = 0, []
    for m in reversed(data[-1]["deplacements"]):
        src, dest = Path(m["src"]), Path(m["dest"])
        if not dest.exists():
            ignores.append(f"{dest.name} : introuvable (déplacé ou supprimé)")
        elif src.exists():
            ignores.append(f"{src.name} : un fichier existe déjà à l'emplacement d'origine")
        else:
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(src))
            restaures += 1
            try:
                dest.parent.rmdir()  # supprime le dossier de tri s'il est vide
            except OSError:
                pass

    _ecrire_journal(journal, data[:-1])
    return restaures, ignores
