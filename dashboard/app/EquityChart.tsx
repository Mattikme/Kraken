"use client";
// Courbe de capital : la stratégie choisie (bleu) contre le buy & hold (gris).
// Les valeurs affichées au-dessus suivent le doigt ou la souris ; au repos, ce sont les dernières.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Point } from "@/lib/data";
import { DASH, eur } from "@/lib/format";

type Props = { main: Point[]; reference: Point[]; mainLabel: string; referenceLabel: string };

const HEIGHT = 230;
const PAD = { top: 10, right: 10, bottom: 24, left: 50 };

/** Graduations « rondes » couvrant [min, max]. */
function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min || 1;
  const raw = span / count;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) ticks.push(t);
  return ticks;
}

function formatDate(ts: number, spanSeconds: number): string {
  const options: Intl.DateTimeFormatOptions =
    spanSeconds > 120 * 86400
      ? { month: "short", year: "2-digit" }
      : spanSeconds > 3 * 86400
        ? { day: "numeric", month: "short" }
        : { hour: "2-digit", minute: "2-digit" }; // période courte : l'heure suffit (la date est au-dessus)
  return new Intl.DateTimeFormat("fr-FR", { ...options, timeZone: "UTC" }).format(new Date(ts * 1000));
}

function formatReadoutDate(ts: number, spanSeconds: number): string {
  const options: Intl.DateTimeFormatOptions =
    spanSeconds > 120 * 86400
      ? { day: "numeric", month: "short", year: "numeric" }
      : { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" };
  const text = new Intl.DateTimeFormat("fr-FR", { ...options, timeZone: "UTC" }).format(new Date(ts * 1000));
  return spanSeconds > 120 * 86400 ? text : `${text} UTC`;
}

export default function EquityChart({ main, reference, mainLabel, referenceLabel }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(340);
  const [active, setActive] = useState<number | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(box.current);
    return () => observer.disconnect();
  }, []);

  const referenceAt = useMemo(() => new Map(reference.map((p) => [p.ts, p.v])), [reference]);
  const enough = main.length >= 2;
  const last = main.length - 1;
  const index = active ?? last;
  const point = main[index];
  const span = enough ? main[last].ts - main[0].ts : 0;

  const readout = (
    <div className="readout" aria-live="off">
      <span className="item">
        <span className="key" />
        {mainLabel} <b>{point ? eur(point.v) : DASH}</b>
      </span>
      <span className="item">
        <span className="key ref" />
        {referenceLabel} <b>{point ? eur(referenceAt.get(point.ts)) : DASH}</b>
      </span>
      <span className="date">{point && enough ? formatReadoutDate(point.ts, span) : DASH}</span>
    </div>
  );

  if (!enough) {
    return (
      <>
        {readout}
        <div className="empty">
          <div>
            <b>{DASH}</b>
            Pas encore assez de points pour tracer une courbe.
          </div>
        </div>
      </>
    );
  }

  const values = [...main.map((p) => p.v), ...reference.map((p) => p.v)];
  const low = Math.min(...values);
  const high = Math.max(...values);
  const margin = (high - low || high * 0.01 || 1) * 0.08;
  const yMin = low - margin;
  const yMax = high + margin;
  const plotWidth = width - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (ts: number) => PAD.left + ((ts - main[0].ts) / span) * plotWidth;
  const y = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * plotHeight;
  const path = (points: Point[]) =>
    points.map((p, i) => `${i ? "L" : "M"}${x(p.ts).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const ticks = niceTicks(yMin, yMax);
  const dateTicks = [0, 1 / 3, 2 / 3, 1].map((f) => main[0].ts + f * span);

  /** Position du pointeur -> point le plus proche (on vise une date, pas une ligne). */
  const pick = (clientX: number, svg: SVGSVGElement) => {
    const rect = svg.getBoundingClientRect();
    const ts = main[0].ts + ((clientX - rect.left - PAD.left) / plotWidth) * span;
    let lo = 0;
    let hi = last;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (main[mid].ts < ts) lo = mid;
      else hi = mid;
    }
    setActive(Math.abs(main[lo].ts - ts) <= Math.abs(main[hi].ts - ts) ? lo : hi);
  };

  const referenceValue = referenceAt.get(point.ts);

  return (
    <>
      {readout}
      <div className="chart" ref={box}>
        <svg
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          role="img"
          tabIndex={0}
          aria-label={`Capital de ${mainLabel} comparé à ${referenceLabel}. Flèches gauche et droite pour parcourir les dates.`}
          onPointerMove={(e) => pick(e.clientX, e.currentTarget)}
          onPointerDown={(e) => pick(e.clientX, e.currentTarget)}
          // Souris : la lecture revient à la dernière valeur en quittant le graphique.
          // Doigt : le point touché reste affiché jusqu'à ce qu'on touche ailleurs.
          onPointerLeave={(e) => e.pointerType === "mouse" && setActive(null)}
          onBlur={() => setActive(null)}
          onKeyDown={(e) => {
            if (e.key === "ArrowLeft") setActive(Math.max(0, index - 1));
            if (e.key === "ArrowRight") setActive(Math.min(last, index + 1));
            if (e.key === "Escape") setActive(null);
          }}
        >
          {ticks.map((t) => (
            <g key={t}>
              <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--line)" strokeWidth="1" />
              <text x={PAD.left - 8} y={y(t) + 3.5} textAnchor="end">
                {eur(t, true)}
              </text>
            </g>
          ))}
          {dateTicks.map((ts, i) => (
            <text
              key={i}
              x={x(ts)}
              y={HEIGHT - 6}
              textAnchor={i === 0 ? "start" : i === dateTicks.length - 1 ? "end" : "middle"}
            >
              {formatDate(ts, span)}
            </text>
          ))}
          <path d={path(reference)} fill="none" stroke="var(--ref)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          <path d={path(main)} fill="none" stroke="var(--blue)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {active !== null && (
            <line x1={x(point.ts)} x2={x(point.ts)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke="var(--ink-2)" strokeWidth="1" />
          )}
          {referenceValue !== undefined && (
            <circle cx={x(point.ts)} cy={y(referenceValue)} r="4.5" fill="var(--ref)" stroke="var(--card)" strokeWidth="2" />
          )}
          <circle cx={x(point.ts)} cy={y(point.v)} r="4.5" fill="var(--blue)" stroke="var(--card)" strokeWidth="2" />
        </svg>
      </div>
    </>
  );
}
