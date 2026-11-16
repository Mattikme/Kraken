"""Point d'entrée : python -m bot <commande>

  run       tourne en continu (passage toutes les 15 min par défaut)
  once      un seul passage : collecte, simulation, rapport
  status    affiche le dernier état enregistré (sans réseau)
  backtest  backtest rapide des stratégies journalières sur données Kraken
"""
import argparse
import json

from . import local


def main():
    parser = argparse.ArgumentParser(prog="python -m bot", description="Bot de trading Kraken en simulation (1 000 € fictifs).")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="tourne en continu")
    run.add_argument("--minutes", type=float, default=15, help="intervalle entre deux passages (défaut 15)")
    sub.add_parser("once", help="un seul passage")
    sub.add_parser("status", help="dernier état enregistré")
    sub.add_parser("backtest", help="backtest rapide sur données Kraken journalières")
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
        print(f"Mis à jour : {state['updated_at']} · BTC/EUR {state['btc_price']:.1f}")
        for r in state["strategies"]:
            print(f"{r['label']:<48}{r['value']:>9.2f} €{r['return']:>+9.2f}%  {r['orders']:>3} ordre(s)  {r['position']}")
    else:
        store = local.open_store()
        local.collect(store)
        local.quick_backtest(store)


if __name__ == "__main__":
    main()
