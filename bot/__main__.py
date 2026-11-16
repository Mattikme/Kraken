"""Point d'entrée : python -m bot <commande>

  run         tourne en continu (passage toutes les 15 min par défaut)
  once        un seul passage : collecte, tournoi, rapport
  status      affiche le dernier classement enregistré (sans réseau)
  historique  tournoi sur 2016 -> aujourd'hui (cours longs, Yahoo Finance)
"""
import argparse
import json

from . import local


def main():
    parser = argparse.ArgumentParser(prog="python -m bot",
                                     description="Tournoi de bots de trading Kraken en simulation (1 000 € fictifs chacun).")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="tourne en continu")
    run.add_argument("--minutes", type=float, default=15, help="intervalle entre deux passages (défaut 15)")
    sub.add_parser("once", help="un seul passage")
    sub.add_parser("status", help="dernier classement enregistré")
    sub.add_parser("historique", help="tournoi sur 10 ans (cours longs)")
    args = parser.parse_args()

    if args.command == "run":
        try:
            local.run_forever(args.minutes)
        except KeyboardInterrupt:
            print("\nBot arrêté. Relance-le quand tu veux : la simulation reprend là où elle en était.")
    elif args.command == "once":
        local.print_status(local.tick(local.open_store()))
        print(f"\nRapport : {local.DATA_DIR / 'rapport.html'}")
    elif args.command == "status":
        path = local.DATA_DIR / "etat.json"
        if not path.exists():
            raise SystemExit("Aucun état : lance d'abord « python -m bot once » ou « python -m bot run ».")
        state = json.loads(path.read_text())
        print(f"Mis à jour {state['updated_at']} · lancement {state['start']}")
        for rank, r in enumerate(state["classement"], 1):
            live = r["depuis_lancement"]
            status = "CANDIDAT AU RÉEL" if r["candidat_reel"] else "en test"
            print(f"{rank:<3}{r['libelle']:<40}{live['final']:>9.2f} €{live['return_pct']:>+8.2f}%  {status} · {r['position']}")
    else:
        store = local.open_store()
        local.download_history(store)
        local.print_history(local.run_history(store))
        print(f"\nRésultat enregistré : {local.DATA_DIR / 'historique.json'} (affiché dans le rapport)")


if __name__ == "__main__":
    main()
