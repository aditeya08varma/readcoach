"use client";

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import type { SessionSummary } from "@/lib/types";

/**
 * Fluency trend: wcpm (line + dots, left axis) and accuracy (line + dots,
 * right axis, 0-100%) across a student's session history. Built directly
 * with D3 (no chart wrapper) per the dashboard's D3 requirement.
 */
export default function FluencyTrendChart({
  sessions,
}: {
  sessions: SessionSummary[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(600);

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
    if (sessions.length === 0) return;

    const height = 320;
    const margin = { top: 24, right: 56, bottom: 40, left: 48 };
    const innerWidth = Math.max(width - margin.left - margin.right, 10);
    const innerHeight = height - margin.top - margin.bottom;

    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", "100%").attr("height", height);

    const data = [...sessions]
      .sort((a, b) => a.started_at.localeCompare(b.started_at))
      .map((s) => ({ ...s, date: new Date(s.started_at) }));

    const g = svg
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    const x = d3
      .scalePoint<Date>()
      .domain(data.map((d) => d.date))
      .range([0, innerWidth])
      .padding(0.5);

    const yWcpm = d3
      .scaleLinear()
      .domain([0, (d3.max(data, (d) => d.wcpm) ?? 0) * 1.15])
      .nice()
      .range([innerHeight, 0]);

    const yAccuracy = d3.scaleLinear().domain([0, 1]).range([innerHeight, 0]);

    // Axes
    // Cap the number of visible x-axis labels by available width (roughly
    // one label per 70px) so dates don't overlap on narrow viewports.
    const maxTicks = Math.max(2, Math.floor(innerWidth / 70));
    const tickStride = Math.ceil(data.length / maxTicks) || 1;
    const tickDates = x.domain().filter((_, i) => i % tickStride === 0);
    // Real feedback: several real sessions seeded within one testing day
    // made this axis show the same "Sep 11" label under 5 of 6 points - a
    // parent would read that as a broken chart, not "your child read five
    // times today." Each tick still gets a real, distinct label: the first
    // tick of a given calendar day shows the date as before, and any later
    // tick that shares that same day shows its time-of-day instead.
    //
    // That first fix wasn't enough on its own: re-checked live against the
    // real backend (not mock data) and every session timestamp genuinely is
    // distinct down to the millisecond - e.g. two quick back-to-back retries
    // on the same passage a few seconds apart. Minute-precision time (the
    // %I:%M %p fallback above) can't tell those two apart, so they rendered
    // as the same label again - a real formatting gap, not a data problem.
    // Guard against that by comparing each candidate label to the previous
    // tick's actual rendered label (not just its calendar day) and, only if
    // they still collide, escalating that one tick to second-precision time.
    const dayFmt = d3.timeFormat("%b %d");
    const timeFmt = (d: Date) => d3.timeFormat("%I:%M %p")(d).replace(/^0/, "");
    const timeSecFmt = (d: Date) => d3.timeFormat("%I:%M:%S %p")(d).replace(/^0/, "");
    const tickLabels = new Map<Date, string>();
    let prevTickDay: string | null = null;
    let prevLabel: string | null = null;
    for (const d of tickDates) {
      const day = dayFmt(d);
      let label = day === prevTickDay ? timeFmt(d) : day;
      if (label === prevLabel) {
        label = timeSecFmt(d);
      }
      tickLabels.set(d, label);
      prevTickDay = day;
      prevLabel = label;
    }
    g.append("g")
      .attr("transform", `translate(0,${innerHeight})`)
      .call(
        d3
          .axisBottom<Date>(x)
          .tickFormat((d) => tickLabels.get(d as Date) ?? "")
          .tickValues(tickDates)
      )
      .call((sel) => sel.selectAll("text").attr("font-size", 11).attr("fill", "#64748b"))
      .call((sel) => sel.select(".domain").attr("stroke", "#cbd5e1"));

    g.append("g")
      .call(d3.axisLeft(yWcpm).ticks(5))
      .call((sel) => sel.selectAll("text").attr("font-size", 11).attr("fill", "#0284c7"))
      .call((sel) => sel.select(".domain").remove())
      .call((sel) => sel.selectAll(".tick line").attr("stroke", "#e2e8f0"));

    g.append("g")
      .attr("transform", `translate(${innerWidth},0)`)
      .call(d3.axisRight(yAccuracy).ticks(5).tickFormat((d) => `${Math.round(+d * 100)}%`))
      .call((sel) => sel.selectAll("text").attr("font-size", 11).attr("fill", "#059669"))
      .call((sel) => sel.select(".domain").remove());

    g.append("text")
      .attr("x", 0)
      .attr("y", -8)
      .attr("font-size", 12)
      .attr("fill", "#0284c7")
      .attr("font-weight", 600)
      .text("WCPM");

    g.append("text")
      .attr("x", innerWidth)
      .attr("y", -8)
      .attr("text-anchor", "end")
      .attr("font-size", 12)
      .attr("fill", "#059669")
      .attr("font-weight", 600)
      .text("Accuracy");

    const wcpmLine = d3
      .line<(typeof data)[number]>()
      .x((d) => x(d.date) ?? 0)
      .y((d) => yWcpm(d.wcpm));

    const accuracyLine = d3
      .line<(typeof data)[number]>()
      .x((d) => x(d.date) ?? 0)
      .y((d) => yAccuracy(d.accuracy));

    // Draw both lines in with a gentle left-to-right reveal rather than
    // popping in fully formed - a small touch that reads as "alive" data,
    // not a static screenshot.
    const wcpmPath = g
      .append("path")
      .datum(data)
      .attr("fill", "none")
      .attr("stroke", "#0284c7")
      .attr("stroke-width", 2.5)
      .attr("d", wcpmLine);
    const wcpmLength = wcpmPath.node()?.getTotalLength() ?? 0;
    wcpmPath
      .attr("stroke-dasharray", `${wcpmLength} ${wcpmLength}`)
      .attr("stroke-dashoffset", wcpmLength)
      .transition()
      .duration(700)
      .ease(d3.easeCubicOut)
      .attr("stroke-dashoffset", 0);

    const accuracyPath = g
      .append("path")
      .datum(data)
      .attr("fill", "none")
      .attr("stroke", "#059669")
      .attr("stroke-width", 2.5)
      .attr("d", accuracyLine);
    const accuracyLength = accuracyPath.node()?.getTotalLength() ?? 0;
    accuracyPath
      .attr("stroke-dasharray", `${accuracyLength} ${accuracyLength}`)
      .attr("stroke-dashoffset", accuracyLength)
      .transition()
      .duration(700)
      .delay(120)
      .ease(d3.easeCubicOut)
      .attr("stroke-dashoffset", 0)
      .on("end", function () {
        // Switch to the dashed style only once the reveal finishes, so the
        // draw-in reads as one continuous stroke rather than dashes racing in.
        d3.select(this).attr("stroke-dasharray", "5,3");
      });

    // Remove any tooltip left over from a previous render of this effect
    // (e.g. triggered by the ResizeObserver) before creating a fresh one -
    // otherwise they'd accumulate as detached-looking but still-live nodes.
    d3.select(containerRef.current).selectAll(".chart-tooltip").remove();
    const tooltip = d3
      .select(containerRef.current)
      .append("div")
      .attr(
        "class",
        "chart-tooltip pointer-events-none absolute z-10 rounded-lg bg-slate-800 px-3 py-2 text-xs text-white opacity-0 shadow-lg transition-opacity"
      );

    g.selectAll(".wcpm-dot")
      .data(data)
      .join("circle")
      .attr("class", "wcpm-dot")
      .attr("cx", (d) => x(d.date) ?? 0)
      .attr("cy", (d) => yWcpm(d.wcpm))
      .attr("r", 4)
      .attr("fill", "#0284c7")
      .style("cursor", "pointer")
      .style("transition", "r 150ms ease")
      .on("mouseenter", function (event, d) {
        d3.select(this).attr("r", 6);
        tooltip
          .style("opacity", 1)
          .html(
            `<div class="font-semibold">${d3.timeFormat("%b %d, %Y")(d.date)}</div>` +
              `<div>${d.wcpm} wcpm · ${Math.round(d.accuracy * 100)}% accuracy</div>` +
              `<div>${d.passage_id}</div>`
          );
      })
      .on("mousemove", (event) => {
        const [px, py] = d3.pointer(event, containerRef.current);
        tooltip.style("left", `${px + 12}px`).style("top", `${py - 12}px`);
      })
      .on("mouseleave", function () {
        d3.select(this).attr("r", 4);
        tooltip.style("opacity", 0);
      });

    g.selectAll(".accuracy-dot")
      .data(data)
      .join("circle")
      .attr("class", "accuracy-dot")
      .attr("cx", (d) => x(d.date) ?? 0)
      .attr("cy", (d) => yAccuracy(d.accuracy))
      .attr("r", 3.5)
      .attr("fill", "#059669");
  }, [sessions, width]);

  return (
    <div ref={containerRef} className="relative w-full">
      <svg ref={svgRef} />
    </div>
  );
}
