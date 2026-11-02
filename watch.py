"""Surveillance en temps réel d'un dossier (nécessite watchdog)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import core


def surveiller(config: dict, dossier, journal: Path, delai: float = 3.0) -> None:
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        raise SystemExit("Le module watchdog est requis : pip install watchdog")

    racine = Path(dossier or config["dossier"]).expanduser()
    if not racine.is_dir():
        raise SystemExit(f"Dossier introuvable : {racine}")

    verrou = threading.Lock()
    minuteur: threading.Timer | None = None

    def ranger() -> None:
        with verrou:
            try:
                plan = core.planifier(config, racine)
                if not plan:
                    return
                for d in plan:
                    print(f"{d.src.name}  ->  {d.dest.parent.name}/{d.dest.name}")
                _, erreurs = core.executer(plan, journal)
                for d, e in erreurs:
                    print(f"Erreur sur {d.src.name} : {e}")
            except Exception as e:  # la surveillance ne doit jamais s'arrêter
                print(f"Erreur : {e}")

    class Gestionnaire(FileSystemEventHandler):
        def _declencher(self) -> None:
            # On attend `delai` secondes après le dernier événement : le fichier
            # a le temps d'être entièrement copié ou téléchargé.
            nonlocal minuteur
            if minuteur is not None:
                minuteur.cancel()
            minuteur = threading.Timer(delai, ranger)
            minuteur.daemon = True
            minuteur.start()

        def on_created(self, event):
            if not event.is_directory:
                self._declencher()

        def on_moved(self, event):  # ex. : .crdownload renommé en fichier final
            if not event.is_directory:
                self._declencher()

    print(f"Surveillance de {racine} (Ctrl+C pour arrêter)")
    ranger()  # range ce qui traîne déjà au démarrage

    observateur = Observer()
    observateur.schedule(Gestionnaire(), str(racine), recursive=False)
    observateur.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observateur.stop()
        observateur.join()
        print("Surveillance arrêtée.")
