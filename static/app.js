const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const btnProcessar = document.getElementById("btnProcessar");
const actionsSection = document.getElementById("actionsSection");
const chartSection = document.getElementById("chartSection");
const btnGerarDanfe = document.getElementById("btnGerarDanfe");
const btnGerarRelatorio = document.getElementById("btnGerarRelatorio");
const chartCanvas = document.getElementById("chartCanvas");
const legendEl = document.getElementById("legend");

let selectedFiles = [];
let chart = null;

// Dropzone
dropzone.addEventListener("click", () => fileInput.click());

dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("drag-over");
});

dropzone.addEventListener("dragleave", () => {
  dropzone.classList.remove("drag-over");
});

dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("drag-over");
  addFiles(e.dataTransfer.files || []);
});

fileInput.addEventListener("change", (e) => {
  addFiles(e.target.files || []);
  e.target.value = "";
});

async function uploadFiles(files) {
  if (files.length === 0) return;
  const formData = new FormData();
  files.forEach((f) => formData.append("xmls", f));
  const res = await fetch("/upload", { method: "POST", body: formData });
  const data = await res.json();
  if (data.ok) {
    btnProcessar.disabled = false;
  } else {
    throw new Error(data.erro || "Falha no envio");
  }
}

function addFiles(files) {
  const xmlFiles = Array.from(files).filter((f) =>
    f.name.toLowerCase().endsWith(".xml")
  );
  if (xmlFiles.length === 0) return;
  uploadFiles(xmlFiles).catch((err) => alert("Erro: " + err.message));
}

// Processar
btnProcessar.addEventListener("click", async () => {
  btnProcessar.disabled = true;
  btnProcessar.innerHTML =
    '<span class="btn-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg></span> Processando...';

  try {
    const res = await fetch("/processar", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      renderChart(data.contagens);
      chartSection.style.display = "block";
      actionsSection.style.display = (data.contagens.AUTORIZADO || 0) > 0 ? "block" : "none";
    } else {
      alert("Erro: " + (data.erro || "Falha ao processar"));
    }
  } catch (err) {
    alert("Erro de conexão: " + err.message);
  }

  btnProcessar.disabled = false;
  btnProcessar.innerHTML =
    '<span class="btn-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg></span> Processar';
});

// Gerar DANFe – download direto (navegador baixa quando o servidor termina de gerar o ZIP)
const progressDanfe = document.getElementById("progressDanfe");
btnGerarDanfe.addEventListener("click", () => {
  const btn = btnGerarDanfe;
  const textoOriginal = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Gerando DANFe...";
  progressDanfe.style.display = "block";

  const a = document.createElement("a");
  a.href = "/gerar-danfe";
  a.download = "danfe.zip";
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);

  setTimeout(() => {
    btn.disabled = false;
    btn.innerHTML = textoOriginal;
    progressDanfe.style.display = "none";
  }, 2000);
});

// Gerar Relatório Imposto
btnGerarRelatorio.addEventListener("click", async () => {
  try {
    const res = await fetch("/relatorio-imposto");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert("Erro: " + (err.erro || "Nenhum XML autorizado encontrado"));
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = res.headers.get("Content-Disposition")?.match(/filename="(.+)"/)?.[1] || "relatorio_impostos.txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    alert("Erro: " + err.message);
  }
});

// Gráfico
const COLORS = {
  AUTORIZADO: "#22c55e",
  INUTILIZADO: "#eab308",
  CANCELADO: "#3b82f6",
  REJEITADO: "#ef4444",
};

function renderChart(contagens) {
  const labels = Object.keys(contagens);
  const values = Object.values(contagens);
  const total = values.reduce((a, b) => a + b, 0);
  const percentages = total > 0 ? values.map((v) => ((v / total) * 100).toFixed(1)) : values.map(() => "0");
  const colors = labels.map((l) => COLORS[l] || "#a1a1aa");

  if (chart) chart.destroy();

  const labelsWithPct = labels.map((l, i) => `${l} (${percentages[i]}%)`);

  const ctx = chartCanvas.getContext("2d");
  chart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labelsWithPct,
      datasets: [
        {
          data: values,
          backgroundColor: colors,
          borderWidth: 2,
          borderColor: "var(--bg-card)",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const pct = total > 0 ? ((ctx.raw / total) * 100).toFixed(1) : 0;
              return `${ctx.label}: ${ctx.raw} (${pct}%)`;
            },
          },
        },
      },
      cutout: "60%",
    },
  });

  // Painel de ações só aparece se houver XML autorizado
  const autorizado = contagens.AUTORIZADO || 0;
  actionsSection.style.display = autorizado > 0 ? "block" : "none";

  legendEl.innerHTML = labels
    .map(
      (l, i) =>
        `<div class="legend-item"><span class="legend-dot" style="background:${colors[i]}"></span><span>${l}: ${values[i]} (${percentages[i]}%)</span></div>`
    )
    .join("");
}
