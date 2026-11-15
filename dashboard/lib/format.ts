// Mise en forme. Règle d'or : une donnée absente s'affiche « — », jamais un faux chiffre.
export const DASH = "—";

const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

const eurFormat = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const eurRound = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });
const pctFormat = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function eur(v: number | null | undefined, round = false): string {
  return isNumber(v) ? `${(round ? eurRound : eurFormat).format(v)} €` : DASH;
}

export function signedEur(v: number | null | undefined): string {
  if (!isNumber(v)) return DASH;
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${eurFormat.format(Math.abs(v))} €`;
}

export function pct(v: number | null | undefined, signed = false): string {
  if (!isNumber(v)) return DASH;
  const sign = signed ? (v > 0 ? "+" : v < 0 ? "−" : "") : "";
  return `${sign}${pctFormat.format(signed ? Math.abs(v) : v)} %`;
}

export function int(v: number | null | undefined): string {
  return isNumber(v) ? String(v) : DASH;
}

export function btc(v: number | null | undefined): string {
  return isNumber(v) ? `${v.toFixed(6).replace(".", ",")} BTC` : DASH;
}

const dateTime = new Intl.DateTimeFormat("fr-FR", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
});
const dateOnly = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** Date et heure en UTC, ex. « 15 nov. 03:00 UTC ». */
export function when(ts: number | null | undefined): string {
  return isNumber(ts) ? `${dateTime.format(new Date(ts * 1000))} UTC` : DASH;
}

export function day(ts: number | null | undefined): string {
  return isNumber(ts) ? dateOnly.format(new Date(ts * 1000)) : DASH;
}

/** Classe de couleur : bleu pour un gain, rouge brique pour une perte. */
export function tone(v: number | null | undefined): string {
  if (!isNumber(v) || v === 0) return "";
  return v > 0 ? "gain" : "loss";
}

export const STRATEGY_LABELS: Record<string, string> = {
  trend_ensemble: "Ensemble de tendances",
  sma_cross_daily_20_50: "Moyennes 20/50 · 1 jour",
  sma_cross_20_50: "Moyennes 20/50 · 1 h",
  momentum_24h: "Momentum 24 h",
  buy_and_hold: "Buy & hold",
};

export const STRATEGY_ORDER = ["trend_ensemble", "sma_cross_daily_20_50", "sma_cross_20_50", "momentum_24h"];

export function label(strategy: string): string {
  return STRATEGY_LABELS[strategy] ?? strategy;
}
