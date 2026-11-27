import type { EmbeddingPoint, Result } from "./types";
import "./embedding-chart.css";

function make<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string) {
  const element = document.createElement(tag);
  if (text) element.textContent = text;
  return element;
}

const groups = { query: "Your query", eo: "EO collections", projects: "Research projects" };

export function renderEmbeddingChart(root: HTMLElement, points: EmbeddingPoint[], results: Result[],
                                     openRecord: (result: Result) => void) {
  const records = new Map(results.map(result => [result.doc.id, result]));
  const introduction = make("p", "A two-dimensional PCA view of your query and the returned records. The map shows a projection, so distances are approximate.");
  introduction.className = "embedding-intro";
  const layout = make("div");
  layout.className = "embedding-layout";
  const plot = make("div");
  plot.className = "embedding-plot";
  plot.role = "group";
  plot.setAttribute("aria-label", "Projected query and result embeddings");
  const horizontal = make("span", "PC 1");
  horizontal.className = "embedding-axis embedding-axis-x";
  const vertical = make("span", "PC 2");
  vertical.className = "embedding-axis embedding-axis-y";
  plot.append(horizontal, vertical);
  const sidebar = make("div");
  sidebar.className = "embedding-sidebar";
  const legend = make("ul");
  legend.className = "embedding-legend";
  for (const [group, label] of Object.entries(groups)) {
    const item = make("li", label);
    item.dataset.group = group;
    legend.append(item);
  }
  const selection = make("div");
  selection.className = "embedding-selection";
  selection.setAttribute("aria-live", "polite");
  sidebar.append(legend, selection);
  layout.append(plot, sidebar);
  root.replaceChildren(introduction, layout);

  const left = Math.min(...points.map(point => point.x));
  const right = Math.max(...points.map(point => point.x));
  const bottom = Math.min(...points.map(point => point.y));
  const top = Math.max(...points.map(point => point.y));
  const scale = 80 / Math.max(right - left, top - bottom, 0.001);
  const dots: HTMLButtonElement[] = [];
  points.forEach((point, i) => {
    const result = point.id === null ? undefined : records.get(point.id);
    const text = result?.doc.title ?? "Your query";
    const dot = make("button");
    dot.type = "button";
    dot.className = "embedding-dot";
    dot.dataset.group = point.group;
    dot.style.left = 50 + (point.x - (left + right) / 2) * scale + "%";
    dot.style.top = 50 - (point.y - (bottom + top) / 2) * scale + "%";
    dot.title = text;
    dot.setAttribute("aria-label", text);
    dot.setAttribute("aria-pressed", "false");

    function select() {
      for (const [j, button] of dots.entries()) button.setAttribute("aria-pressed", String(i === j));
      const name = make("strong", text);
      const detail = make("p", result ? "Similarity score " + result.score.toFixed(3) : "The text you searched for.");
      selection.replaceChildren(name, detail);
      if (result) {
        const visit = make("button", "View result");
        visit.type = "button";
        visit.className = "extent-button";
        visit.addEventListener("click", () => openRecord(result));
        selection.append(visit);
      }
    }

    dots.push(dot);
    dot.addEventListener("click", select);
    plot.append(dot);
    if (point.id === null) select();
  });
}
