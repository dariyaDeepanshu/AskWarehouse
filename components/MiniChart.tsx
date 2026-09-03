"use client";

import type { ChartData } from "@/lib/types";

function fmt(n: number): string {
  const a = Math.abs(n);
  if (a >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (a >= 1e3) return (n / 1e3).toFixed(1) + "k";
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
}

export default function MiniChart({ chart }: { chart: ChartData }) {
  if (chart.kind !== "bar" && chart.kind !== "line") return null;

  const W = 780;
  const H = 300;
  const padL = 64;
  const padR = 16;
  const padT = 14;
  const padB = 78;
  const iw = W - padL - padR;
  const ih = H - padT - padB;

  const values = chart.values;
  const labels = chart.labels;
  const n = values.length;
  const maxV = Math.max(0, ...values);
  const minV = Math.min(0, ...values);
  const span = maxV - minV || 1;
  const y = (v: number) => padT + ih - ((v - minV) / span) * ih;

  const ticks = 4;
  const gridLines = Array.from({ length: ticks + 1 }, (_, i) => minV + (span * i) / ticks);

  const showEvery = Math.ceil(n / 12);

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${chart.y_label} by ${chart.x_label}`}>
        {gridLines.map((gv, i) => (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={y(gv)} y2={y(gv)} stroke="#e4e7eb" />
            <text x={padL - 8} y={y(gv) + 4} textAnchor="end" fontSize="11" fill="#5b636e">
              {fmt(gv)}
            </text>
          </g>
        ))}

        {chart.kind === "bar" &&
          values.map((v, i) => {
            const bw = (iw / n) * 0.68;
            const bx = padL + (iw / n) * i + (iw / n - bw) / 2;
            const y0 = y(Math.max(0, minV));
            const y1 = y(v);
            return (
              <rect
                key={i}
                x={bx}
                y={Math.min(y0, y1)}
                width={bw}
                height={Math.max(1, Math.abs(y1 - y0))}
                fill="#2f6f4f"
                rx="2"
              >
                <title>{`${labels[i]}: ${fmt(v)}`}</title>
              </rect>
            );
          })}

        {chart.kind === "line" && (
          <>
            <polyline
              fill="none"
              stroke="#2f6f4f"
              strokeWidth="2"
              points={values
                .map((v, i) => `${padL + (iw / Math.max(1, n - 1)) * i},${y(v)}`)
                .join(" ")}
            />
            {values.map((v, i) => (
              <circle
                key={i}
                cx={padL + (iw / Math.max(1, n - 1)) * i}
                cy={y(v)}
                r="2.6"
                fill="#2f6f4f"
              >
                <title>{`${labels[i]}: ${fmt(v)}`}</title>
              </circle>
            ))}
          </>
        )}

        {labels.map((lb, i) => {
          if (i % showEvery !== 0 && i !== n - 1) return null;
          const cx =
            chart.kind === "bar"
              ? padL + (iw / n) * i + iw / n / 2
              : padL + (iw / Math.max(1, n - 1)) * i;
          return (
            <text
              key={i}
              x={cx}
              y={H - padB + 16}
              textAnchor="end"
              fontSize="11"
              fill="#5b636e"
              transform={`rotate(-40 ${cx} ${H - padB + 16})`}
            >
              {lb.length > 18 ? lb.slice(0, 17) + "…" : lb}
            </text>
          );
        })}

        <text x={(padL + W - padR) / 2} y={H - 6} textAnchor="middle" fontSize="11.5" fill="#1a1d21">
          {chart.x_label}
        </text>
        <text
          x={14}
          y={(padT + ih / 2)}
          textAnchor="middle"
          fontSize="11.5"
          fill="#1a1d21"
          transform={`rotate(-90 14 ${padT + ih / 2})`}
        >
          {chart.y_label}
        </text>
      </svg>
    </div>
  );
}

export { fmt };
