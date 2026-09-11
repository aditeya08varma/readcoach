"use client";

import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import type { MasterySkill } from "@/lib/types";

const CATEGORY_COLOR: Record<string, string> = {
  phonics: "#0284c7",
  vocabulary: "#d97706",
  comprehension: "#7c3aed",
};

/**
 * Skill mastery as a horizontal bar chart, grouped by category and sorted by
 * weight within category — reads more clearly than a radar chart once there
 * are 15+ skills in the taxonomy (see content/skill_taxonomy.json).
 */
export default function MasteryBarChart({ skills }: { skills: MasterySkill[] }) {
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
    if (skills.length === 0) return;

    const data = [...skills].sort((a, b) => {
      if (a.category !== b.category) return a.category.localeCompare(b.category);
      return b.weight - a.weight;
    });

    // The label column is a fixed 200px on comfortable widths, but that alone
    // eats the whole chart on a phone (e.g. it leaves just 10px for 18 bars
    // at 320px wide) - so below 480px it shrinks with the container instead,
    // and labels that no longer fit get truncated below rather than pushing
    // the bar track to nothing.
    const isCompact = width < 480;
    const margin = {
      top: 8,
      right: isCompact ? 28 : 44,
      bottom: 8,
      left: isCompact ? Math.max(72, Math.min(140, Math.round(width * 0.34))) : 200,
    };
    const rowHeight = 26;
    const innerWidth = Math.max(width - margin.left - margin.right, 10);
    const innerHeight = data.length * rowHeight;
    const height = innerHeight + margin.top + margin.bottom;

    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", "100%").attr("height", height);

    const g = svg
      .append("g")
      .attr("transform", `translate(${margin.left},${margin.top})`);

    const y = d3
      .scaleBand()
      .domain(data.map((d) => d.skill_id))
      .range([0, innerHeight])
      .padding(0.25);

    const x = d3.scaleLinear().domain([0, 1]).range([0, innerWidth]);

    g.selectAll(".track")
      .data(data)
      .join("rect")
      .attr("class", "track")
      .attr("x", 0)
      .attr("y", (d) => y(d.skill_id) ?? 0)
      .attr("width", innerWidth)
      .attr("height", y.bandwidth())
      .attr("rx", 4)
      .attr("fill", "#f1f5f9");

    g.selectAll(".bar")
      .data(data)
      .join("rect")
      .attr("class", "bar")
      .attr("x", 0)
      .attr("y", (d) => y(d.skill_id) ?? 0)
      .attr("width", 0)
      .attr("height", y.bandwidth())
      .attr("rx", 4)
      .attr("fill", (d) => CATEGORY_COLOR[d.category] ?? "#64748b")
      .transition()
      .duration(500)
      .delay((_, i) => i * 25)
      .ease(d3.easeCubicOut)
      .attr("width", (d) => x(d.weight));

    g.selectAll(".value-label")
      .data(data)
      .join("text")
      .attr("class", "value-label")
      .attr("x", (d) => x(d.weight) + 6)
      .attr("y", (d) => (y(d.skill_id) ?? 0) + y.bandwidth() / 2)
      .attr("dy", "0.35em")
      .attr("font-size", 11)
      .attr("fill", "#475569")
      .text((d) => `${Math.round(d.weight * 100)}%`);

    const labelSelection = g
      .selectAll<SVGTextElement, (typeof data)[number]>(".label")
      .data(data)
      .join("text")
      .attr("class", "label")
      .attr("x", -8)
      .attr("y", (d) => (y(d.skill_id) ?? 0) + y.bandwidth() / 2)
      .attr("dy", "0.35em")
      .attr("text-anchor", "end")
      .attr("font-size", 12)
      .attr("fill", "#334155")
      .text((d) => d.label);

    // Some skill labels (e.g. "Inflectional Endings (-s, -ed, -ing)") are
    // long enough to run into the bar track even at the full 200px column,
    // and much more so once that column has shrunk for a phone-width
    // screen. Trim to fit and expose the full label via <title> instead of
    // letting it overlap the chart.
    const labelMaxWidth = margin.left - 12;
    labelSelection.each(function (d) {
      const node = d3.select(this);
      const el = node.node();
      if (!el || el.getComputedTextLength() <= labelMaxWidth) return;
      let text = d.label;
      while (text.length > 1 && el.getComputedTextLength() > labelMaxWidth) {
        text = text.slice(0, -1);
        node.text(`${text}…`);
      }
      node.append("title").text(d.label);
    });
  }, [skills, width]);

  return (
    <div ref={containerRef} className="w-full overflow-x-auto">
      <svg ref={svgRef} />
    </div>
  );
}
