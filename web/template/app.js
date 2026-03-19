const fmt = new Intl.NumberFormat("en-US");
let scoreChartInstance = null;

function statusClass(status) {
  if (status === "completed") return "status-completed";
  if (status === "failed") return "status-failed";
  return "status-other";
}

function pretty(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return value;
}

function scoreText(score) {
  return typeof score === "number" ? score.toFixed(4) : "-";
}

function renderKpis(summary) {
  const totals = summary.totals || {};
  const items = [
    ["Total Experiments", pretty(totals.total, 0)],
    ["Completed", pretty(totals.completed, 0)],
    ["Failed", pretty(totals.failed, 0)],
    ["Not Run", pretty(totals.not_run, 0)],
    ["Average Score", totals.average_final_score == null ? "-" : totals.average_final_score.toFixed(4)],
  ];

  const host = document.getElementById("kpiGrid");
  host.innerHTML = "";

  for (const [label, value] of items) {
    const el = document.createElement("article");
    el.className = "kpi";
    el.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div>`;
    host.appendChild(el);
  }
}

function renderTable(summary) {
  const tbody = document.querySelector("#summaryTable tbody");
  tbody.innerHTML = "";

  for (const item of summary.experiments || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><code>${pretty(item.id)}</code></td>
      <td>${pretty(item.title)}</td>
      <td><span class="status-pill ${statusClass(item.status)}">${pretty(item.status)}</span></td>
      <td>${scoreText(item.final_score)}</td>
      <td>${pretty(item.rounds, 0)}</td>
      <td>${item.latency_total_sec == null ? "-" : Number(item.latency_total_sec).toFixed(2)}</td>
      <td>${item.total_tokens == null ? "-" : fmt.format(item.total_tokens)}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderCards(summary, previews) {
  const host = document.getElementById("cards");
  host.innerHTML = "";
  const frag = document.createDocumentFragment();

  for (const item of summary.experiments || []) {
    const raw = previews[item.slug] || {};
    const card = document.createElement("article");
    card.className = "card";
    const preview = pretty(raw.preview, "No raw output yet.");
    const clippedPreview = preview.length > 700 ? `${preview.slice(0, 700)}\n... (truncated)` : preview;

    card.innerHTML = `
      <h3>${pretty(item.id)} · ${pretty(item.title)}</h3>
      <p class="subtle">Status: ${pretty(item.status)} | Score: ${scoreText(item.final_score)}</p>
      <pre>${clippedPreview}</pre>
    `;

    frag.appendChild(card);
  }

  host.appendChild(frag);
}

function renderChart(summary) {
  const items = summary.experiments || [];
  const labels = items.map((x) => x.id || x.slug || "N/A");
  const scoreData = items.map((x) => {
    const value = Number(x.final_score);
    return Number.isFinite(value) ? value : 0;
  });

  const ctx = document.getElementById("scoreChart");
  if (!ctx || typeof window.Chart === "undefined") return;

  if (scoreChartInstance) {
    scoreChartInstance.destroy();
  }

  scoreChartInstance = new window.Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Final Score",
          data: scoreData,
          maxBarThickness: 34,
          categoryPercentage: 0.72,
          barPercentage: 0.86,
          borderWidth: 1,
          backgroundColor: "rgba(108, 229, 216, 0.55)",
          borderColor: "rgba(108, 229, 216, 1)",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      normalized: true,
      scales: {
        y: {
          beginAtZero: true,
          max: 1,
          grid: { color: "rgba(141, 176, 227, 0.15)" },
        },
        x: {
          grid: { display: false },
        },
      },
      plugins: {
        legend: { labels: { color: "#dbe8ff" } },
      },
    },
  });
}

async function bootstrap() {
  const generatedAt = document.getElementById("generatedAt");

  try {
    const res = await fetch("./data.json", { cache: "no-cache" });
    if (!res.ok) {
      throw new Error(`Cannot load data.json (${res.status})`);
    }

    const payload = await res.json();
    const summary = payload.summary || { totals: {}, experiments: [] };
    const previews = payload.raw_previews || {};

    generatedAt.textContent = `Generated at ${payload.generated_at || "unknown"}`;

    renderKpis(summary);
    renderTable(summary);
    renderCards(summary, previews);
    renderChart(summary);
  } catch (err) {
    generatedAt.textContent = `Failed to load dashboard data: ${err}`;
  }
}

bootstrap();
