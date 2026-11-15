// Tableau de bord : une seule page, rendue à chaque visite à partir de Neon.
import Link from "next/link";
import EquityChart from "./EquityChart";
import { loadData, type Data, type Mode, type Result } from "@/lib/data";
import { DASH, btc, day, eur, int, label, pct, signedEur, STRATEGY_ORDER, tone, when } from "@/lib/format";

export const dynamic = "force-dynamic"; // jamais de page figée : on relit Neon à chaque fois

const REFERENCE = "buy_and_hold";
const SIGNAL_LABELS: Record<string, string> = { BUY: "acheter", SELL: "vendre", HOLD: "rien" };
const EMPTY: Data = { results: [], equity: {}, trades: [], lastCandle: null, signals: [] };

type Search = Promise<{ mode?: string; s?: string }>;

export default async function Page({ searchParams }: { searchParams: Search }) {
  const params = await searchParams;
  const mode: Mode = params.mode === "backtest" ? "backtest" : "paper";
  const strategy = STRATEGY_ORDER.includes(params.s ?? "") ? (params.s as string) : STRATEGY_ORDER[0];
  const href = (m: Mode, s: string) => `/?mode=${m}&s=${s}`;

  let data = EMPTY;
  let failed = false;
  try {
    data = await loadData(mode, [strategy, REFERENCE]);
  } catch (error) {
    console.error(error);
    failed = true;
  }

  const byName = new Map(data.results.map((r) => [r.strategy, r]));
  const current = byName.get(strategy);
  const reference = byName.get(REFERENCE);
  const net = current ? current.final_eur - current.start_eur : null;
  const gap = current && reference ? current.final_eur - reference.final_eur : null;
  const signal = data.signals.find((s) => s.strategy === strategy);
  const anyResult = current ?? reference ?? data.results[0];
  const isPaper = mode === "paper";

  return (
    <main className="wrap">
      <header className="card top">
        <div>
          <p className="label">Kraken · sans levier</p>
          <h1>BTC/EUR</h1>
        </div>
        <div className="top-right">
          {isPaper ? (
            <span className="chip live">
              <i />
              Simulation
            </span>
          ) : (
            <span className="chip">Backtest</span>
          )}
          <span className="stamp">Calculé le {when(anyResult?.run_at)}</span>
        </div>
      </header>

      <nav className="tabs" aria-label="Type de résultat">
        <Link href={href("paper", strategy)} aria-current={isPaper ? "page" : undefined}>
          Simulation en direct
        </Link>
        <Link href={href("backtest", strategy)} aria-current={!isPaper ? "page" : undefined}>
          Backtest 2 ans
        </Link>
      </nav>

      <nav className="pills" aria-label="Stratégie">
        {STRATEGY_ORDER.map((s) => (
          <Link key={s} href={href(mode, s)} aria-current={s === strategy ? "page" : undefined}>
            {label(s)}
          </Link>
        ))}
      </nav>

      {failed && (
        <section className="card">
          <p className="label">Données indisponibles</p>
          <p className="note">La base Neon n&apos;a pas répondu. Aucun chiffre n&apos;est affiché plutôt qu&apos;un chiffre faux.</p>
        </section>
      )}

      <section className="card" aria-label="Résultat de la stratégie">
        <p className="label">Gain net après frais · {label(strategy)}</p>
        <p className={`hero-figure ${tone(net)}`}>{signedEur(net)}</p>
        <div className="hero-chips">
          <span className="chip">Capital {eur(current?.final_eur)}</span>
          <span className={`chip ${tone(current?.return_pct)}`}>{pct(current?.return_pct, true)}</span>
          <span className={`chip ${tone(gap)}`}>vs buy &amp; hold {signedEur(gap)}</span>
          {isPaper && <span className="chip">Position {current?.position ?? DASH}</span>}
          {isPaper && <span className="chip">Dernier signal {signal ? SIGNAL_LABELS[signal.signal] ?? signal.signal : DASH}</span>}
        </div>
        <dl className="stats">
          <div>
            <dt className="label">Ordres</dt>
            <dd>
              {int(current?.n_trades)}
              <small>{current ? `${current.n_round_trips} aller(s)-retour(s) clôturé(s)` : DASH}</small>
            </dd>
          </div>
          <div>
            <dt className="label">Taux de réussite</dt>
            <dd>
              {pct(current?.win_rate_pct)}
              <small>allers-retours gagnants</small>
            </dd>
          </div>
          <div>
            <dt className="label">Frais payés</dt>
            <dd>
              {eur(current?.fees_eur)}
              <small>frais preneur Kraken</small>
            </dd>
          </div>
          <div>
            <dt className="label">Pire baisse</dt>
            <dd>
              {pct(current?.max_drawdown_pct)}
              <small>depuis un sommet (drawdown)</small>
            </dd>
          </div>
        </dl>
      </section>

      <section className="card" aria-label="Courbe de capital">
        <h2>Capital</h2>
        <p className="sub">
          {anyResult ? `Départ ${eur(anyResult.start_eur, true)} le ${day(anyResult.start_ts)}` : `Départ ${DASH}`}
          {isPaper ? " · argent fictif" : " · historique rejoué"}
        </p>
        <EquityChart
          main={data.equity[strategy] ?? []}
          reference={data.equity[REFERENCE] ?? []}
          mainLabel={label(strategy)}
          referenceLabel={label(REFERENCE)}
        />
      </section>

      <section className="card" aria-label="Comparaison des stratégies">
        <h2>Toutes les stratégies</h2>
        <p className="sub">
          {anyResult ? `Du ${day(anyResult.start_ts)} au ${isPaper ? when(anyResult.end_ts) : day(anyResult.end_ts)}` : DASH} · après frais
          et glissement
        </p>
        <ul className="compare">
          {[...STRATEGY_ORDER, REFERENCE].map((name) => {
            const r: Result | undefined = byName.get(name);
            const gain = r ? r.final_eur - r.start_eur : null;
            return (
              <li key={name} className={name === strategy ? "current" : undefined}>
                <span className="name">
                  {name === REFERENCE ? label(name) : <Link href={href(mode, name)}>{label(name)}</Link>}
                </span>
                <span className="capital">{eur(r?.final_eur)}</span>
                <span className="details">
                  <span className={tone(gain)}>{signedEur(gain)}</span>
                  <span>{int(r?.n_trades)} ordre(s)</span>
                  <span>réussite {pct(r?.win_rate_pct)}</span>
                  <span>pire baisse {pct(r?.max_drawdown_pct)}</span>
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="card" aria-label="Derniers ordres">
        <h2>Derniers ordres</h2>
        <p className="sub">Toutes stratégies · prix d&apos;exécution, glissement de 0,05 % inclus</p>
        {data.trades.length === 0 ? (
          <div className="empty">
            <div>
              <b>{DASH}</b>
              Aucun ordre pour l&apos;instant.
            </div>
          </div>
        ) : (
          <ul className="trades">
            {data.trades.map((t) => (
              <li key={`${t.strategy}-${t.ts}`}>
                <span className={`side ${t.side}`}>{t.side === "buy" ? "ACHAT" : "VENTE"}</span>
                <span className="what">{label(t.strategy)}</span>
                <span className="amount">{eur(t.price)}</span>
                <small className="date">{when(t.ts)}</small>
                <small className="fee">
                  <span className="wide">{btc(t.qty)} · </span>frais {eur(t.fee)}
                </small>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer>
        <span>
          Dernière bougie 1 h reçue : clôture du {when(data.lastCandle ? data.lastCandle.ts + 3600 : null)} à{" "}
          {eur(data.lastCandle?.close)}.
        </span>
        <span>
          Tous les chiffres viennent de la base Neon. {isPaper ? "Simulation : aucun argent réel n'est engagé." : "Backtest : les performances passées ne préjugent pas des performances futures."}
        </span>
      </footer>
    </main>
  );
}
