/**
 * Dashboard & Visualization Charts using Chart.js
 */

// Pipeline progress poller
function startPipelinePoller(ideaId, targetRedirectUrl) {
    const progressContainer = document.getElementById("pipelineProgressOverlay");
    const progressBar = document.getElementById("pipelineProgressBar");
    const progressStatus = document.getElementById("pipelineProgressStatus");

    if (!progressContainer || !progressBar) return;

    progressContainer.classList.remove("d-none");

    const poller = setInterval(async () => {
        try {
            const res = await fetch(`/api/idea/${ideaId}/status`);
            if (res.ok) {
                const data = await res.json();
                const prog = data.progress || {};
                const percent = prog.percent || 15;
                progressBar.style.width = `${percent}%`;
                progressBar.textContent = `${percent}%`;
                if (progressStatus) progressStatus.textContent = prog.message || "Analyzing startup metrics...";

                if (prog.status === "completed" || data.status === "completed") {
                    clearInterval(poller);
                    progressBar.style.width = "100%";
                    progressBar.textContent = "100%";
                    if (progressStatus) progressStatus.textContent = "Validation Complete! Loading results...";
                    setTimeout(() => {
                        window.location.href = targetRedirectUrl || `/idea/${ideaId}/report`;
                    }, 1200);
                } else if (prog.status === "failed" || data.status === "failed") {
                    clearInterval(poller);
                    if (progressStatus) progressStatus.textContent = (prog.message || "Validation halted with an error.") + " Open the report to re-run.";
                    progressBar.classList.remove("progress-bar-animated", "progress-bar-striped", "bg-info");
                    progressBar.classList.add("bg-danger");
                    setTimeout(() => { window.location.reload(); }, 4000);
                }
            }
        } catch (e) {
            console.error("Poller error", e);
        }
    }, 1500);
}

// Viability Dimensions Radar Chart
function renderViabilityRadar(canvasId, scores) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    new Chart(ctx, {
        type: 'radar',
        data: {
            labels: ['Market Demand', 'Competitive Position', 'Execution', 'Business Model', 'Risk Resistance'],
            datasets: [{
                label: 'Startup Validation Score',
                data: [
                    scores.market ?? 0,
                    scores.competition ?? 0,
                    scores.execution ?? 0,
                    scores.business ?? 0,
                    scores.riskResistance ?? 0
                ],
                backgroundColor: 'rgba(37, 99, 235, 0.2)',
                borderColor: '#2563eb',
                borderWidth: 2,
                pointBackgroundColor: '#1e40af',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: '#1e40af'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                r: {
                    angleLines: { color: '#e2e8f0' },
                    grid: { color: '#e2e8f0' },
                    suggestedMin: 0,
                    suggestedMax: 100,
                    ticks: { stepSize: 20, font: { size: 10 } }
                }
            },
            plugins: {
                legend: { display: false }
            }
        }
    });
}

// Category Distribution Doughnut Chart
function renderCategoryChart(canvasId, labels, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels || [],
            datasets: [{
                data: data || [],
                backgroundColor: ['#2563eb', '#38bdf8', '#10b981', '#f59e0b'],
                borderWidth: 2,
                borderColor: '#ffffff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } }
            },
            cutout: '70%'
        }
    });
}


// Re-run the analysis for an idea (used by "Re-run analysis" buttons)
async function rerunAnalysis(ideaId, button) {
    if (button) { button.disabled = true; button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Starting...'; }
    try {
        const res = await fetch(`/api/idea/${ideaId}/run`, { method: "POST" });
        if (res.ok || res.status === 409) { window.location.reload(); return; }
        alert("Could not start the analysis.");
    } catch (e) { alert("Network error while starting the analysis."); }
    if (button) { button.disabled = false; button.textContent = "Re-run analysis"; }
}
