"""Interface en ligne de commande de DeskOrg."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, core


def cmd_trier(args, config) -> int:
    plan = core.planifier(config, args.dossier)
    if not plan:
        print("Rien à ranger.")
        return 0

    for d in plan:
        note = f"  [{d.note}]" if d.note else ""
        print(f"{d.src.name}  ->  {d.dest.parent.name}/{d.dest.name}{note}")

    if not args.appliquer:
        print(f"\nSimulation : {len(plan)} fichier(s). Ajoute --appliquer pour les déplacer.")
        return 0

    nb, erreurs = core.executer(plan, args.journal)
    print(f"\n{nb} fichier(s) déplacé(s). Pour revenir en arrière : deskorg annuler")
    for d, e in erreurs:
        print(f"Erreur sur {d.src.name} : {e}", file=sys.stderr)
    return 1 if erreurs else 0


def cmd_annuler(args, config) -> int:
    resultat = core.annuler(args.journal)
    if resultat is None:
        print("Rien à annuler.")
        return 0
    restaures, ignores = resultat
    print(f"{restaures} fichier(s) remis en place.")
    for msg in ignores:
        print(f"Ignoré : {msg}", file=sys.stderr)
    return 0


def cmd_historique(args, config) -> int:
    data = core.lire_journal(args.journal)
    if not data:
        print("Journal vide.")
        return 0
    for i, op in enumerate(data, 1):
        print(f"{i}. {op['date']}  -  {len(op['deplacements'])} fichier(s)")
    return 0


def cmd_surveiller(args, config) -> int:
    from .watch import surveiller

    surveiller(config, args.dossier, args.journal, args.delai)
    return 0


def cmd_init(args, config) -> int:
    chemin = args.config or core.CONFIG_PATH
    if Path(chemin).exists():
        print(f"{chemin} existe déjà, rien n'a été modifié.")
        return 1
    core.ecrire_config_defaut(chemin)
    print(f"Configuration créée : {chemin}")
    return 0


def construire_parseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deskorg", description="Range automatiquement les fichiers de ton bureau."
    )
    p.add_argument("--version", action="version", version=f"deskorg {__version__}")
    p.add_argument("--config", type=Path, help="fichier de configuration JSON")
    p.add_argument(
        "--journal", type=Path, default=core.JOURNAL_PATH, help="fichier du journal"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("trier", help="range le dossier (simulation par défaut)")
    t.add_argument("dossier", nargs="?", help="par défaut : le dossier de la config")
    t.add_argument("--appliquer", action="store_true", help="déplace réellement les fichiers")
    t.set_defaults(fn=cmd_trier)

    a = sub.add_parser("annuler", help="annule la dernière opération")
    a.set_defaults(fn=cmd_annuler)

    h = sub.add_parser("historique", help="liste les opérations du journal")
    h.set_defaults(fn=cmd_historique)

    s = sub.add_parser("surveiller", help="range automatiquement les nouveaux fichiers")
    s.add_argument("dossier", nargs="?")
    s.add_argument("--delai", type=float, default=3.0, help="secondes d'attente (défaut : 3)")
    s.set_defaults(fn=cmd_surveiller)

    i = sub.add_parser("init", help="crée le fichier de configuration par défaut")
    i.set_defaults(fn=cmd_init)
    return p


def main(argv=None) -> int:
    args = construire_parseur().parse_args(argv)
    try:
        config = core.charger_config(args.config) if args.cmd != "init" else None
        return args.fn(args, config)
    except (OSError, ValueError) as e:  # fichier absent, JSON invalide, dossier introuvable
        print(f"Erreur : {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
