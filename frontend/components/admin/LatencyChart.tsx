"use client";

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import type { EngineeringDashboard } from "@/lib/types";

/** Grouped bar chart: P50 vs P95 latency per pipeline stage (stt/llm/tts). */
export default function LatencyChart({
  dashboard,
}: {
  dashboard: EngineeringDashboard;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(500);

  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const stages = ["stt_ms", "llm_ms", "tts_ms"] as const;
    // stt_ms/tts_ms can be null (not measured yet, honestly - see
    // lib/types.ts). Treat as 0-height bars rather than NaN, which is what
    // a d3 scale does with a raw null and silently drops the rect.
    const data = stages.map((stage) => ({
      stage,
      label: stage.replace("_ms", "").toUpperCase(),
      p50: dashboard.latency_p50_ms[stage] ?? 0,
      p95: dashboard.latency_p95_ms[stage] ?? 0,
      measured: dashboard.latency_p95_ms[stage] !== null,
    }));

    const height = 260;
    const margin = { top: 16, right: 16, bottom: 32, left: 48 };
    const innerWidth = Math.max(width - margin.left - margin.right, 10);
    const innerHeight = height - margin.top - margin.bottom;

    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", "100%").attr("height", height);

    const g = svg
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    const x0 = d3
      .scaleBand()
      .domain(data.map((d) => d.label))
      .range([0, innerWidth])
      .padding(0.3);

    const x1 = d3
      .scaleBand()
      .domain(["p50", "p95"])
      .range([0, x0.bandwidth()])
      .padding(0.15);

    const y = d3
      .scaleLinear()
      .domain([0, (d3.max(data, (d) => d.p95) ?? 0) * 1.15])
      .nice()
      .range([innerHeight, 0]);

    const color = { p50: "#0284c7", p95: "#f97316" };

    g.append("g")
      .attr("transform", `translate(0,${innerHeight})`)
      .call(d3.axisBottom(x0))
      .call((sel) => sel.selectAll("text").attr("font-size", 12).attr("fill", "#334155"))
      .call((sel) => sel.select(".domain").attr("stroke", "#cbd5e1"));

    g.append("g")
      .call(d3.axisLeft(y).ticks(5).tickFormat((d) => `${d}ms`))
      .call((sel) => sel.selectAll("text").attr("font-size", 11).attr("fill", "#64748b"))
      .call((sel) => sel.select(".domain").remove())
      .call((sel) => sel.selectAll(".tick line").attr("stroke", "#e2e8f0"));

    const stageGroups = g
      .selectAll(".stage-group")
      .data(data)
      .join("g")
      .attr("class", "stage-group")
      .attr("transform", (d) => `translate(${x0(d.label)},0)`);

    (["p50", "p95"] as const).forEach((metric) => {
      stageGroups
        .append("rect")
        .attr("x", x1(metric) ?? 0)
        .attr("y", (d) => y(d[metric]))
        .attr("width", x1.bandwidth())
        .attr("height", (d) => innerHeight - y(d[metric]))
        .attr("rx", 3)
        .attr("fill", color[metric]);

      stageGroups
        .append("text")
        .attr("x", (x1(metric) ?? 0) + x1.bandwidth() / 2)
        .attr("y", (d) => y(d[metric]) - 6)
        .attr("text-anchor", "middle")
        .attr("font-size", 10)
        .attr("fill", "#475569")
        .text((d) => (d.measured ? `${d[metric]}` : "n/a"));
    });
  }, [dashboard, width]);

  return (
    <div ref={containerRef} className="w-full">
      <svg ref={svgRef} />
      <div className="mt-2 flex gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-[#0284c7]" /> P50
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-[#f97316]" /> P95
        </span>
      </div>
    </div>
  );
}
