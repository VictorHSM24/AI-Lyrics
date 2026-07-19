// Sprint 15.2 — verifica HealthPanel com dados reais do backend.
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  console.log("[STEP] Navegando para http://localhost:5173/sobre...");
  await page.goto("http://localhost:5173/sobre", { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(5000); // Wait for health polling.

  // Verificar itens do HealthPanel.
  const items = await page.$$eval('[data-testid="health-item"]', (els) =>
    els.map((el) => ({
      id: el.getAttribute("data-item-id"),
      status: el.getAttribute("data-status"),
      text: el.textContent?.trim().replace(/\s+/g, " "),
    })),
  );

  console.log("\n[CHECK] HealthPanel items:");
  for (const item of items) {
    console.log(`  ${item.id}: ${item.status} — ${item.text}`);
  }

  // Verificar Holyrics especificamente.
  const holyricsItem = items.find((i) => i.id === "holyrics");
  console.log(`\n[CHECK] Holyrics: ${holyricsItem?.status} — ${holyricsItem?.text}`);

  // Verificar Backend.
  const backendItem = items.find((i) => i.id === "backend");
  console.log(`[CHECK] Backend: ${backendItem?.status} — ${backendItem?.text}`);

  // Verificar Microfone.
  const micItem = items.find((i) => i.id === "microphone");
  console.log(`[CHECK] Microfone: ${micItem?.status} — ${micItem?.text}`);

  // Verificar STT.
  const sttItem = items.find((i) => i.id === "stt");
  console.log(`[CHECK] STT: ${sttItem?.status} — ${sttItem?.text}`);

  await page.screenshot({ path: "_diag_health.png", fullPage: true });
  console.log("\n[STEP] Screenshot salvo em _diag_health.png");

  await browser.close();
}

main().catch(console.error);
