// Diagnóstico Sprint 15.1 — testa frontend com Playwright (v2).
// Avalia estado dos stores diretamente via JavaScript.
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const consoleLogs = [];
  page.on("console", (msg) => {
    const text = msg.text();
    consoleLogs.push(`[${msg.type()}] ${text}`);
    if (text.includes("audio") || text.includes("Audio") || text.includes("bridge")) {
      console.log(`  [CONSOLE] ${text}`);
    }
  });

  const pageErrors = [];
  page.on("pageerror", (err) => {
    pageErrors.push(err.message);
    console.log(`  [PAGE ERROR] ${err.message}`);
  });

  const wsLogs = [];
  page.on("websocket", (ws) => {
    wsLogs.push(`WS opened: ${ws.url()}`);
    ws.on("framereceived", (frame) => {
      const text = typeof frame.payload === "string" ? frame.payload : JSON.stringify(frame.payload);
      if (text.includes("audio")) {
        // Parse to get event_type.
        try {
          const msg = JSON.parse(text);
          const et = msg.event?.event_type || "?";
          wsLogs.push(`WS recv: ${et}`);
        } catch {
          wsLogs.push(`WS recv: (parse error)`);
        }
      }
    });
  });

  console.log("[STEP] Navegando para http://localhost:5173/configuracoes...");
  // Use a cache-busting URL to force fresh module loads.
  const context = browser.newContext({ bypassCSP: true });
  await page.goto("http://localhost:5173/configuracoes?v=" + Date.now(), { waitUntil: "networkidle", timeout: 15000 });
  await page.waitForTimeout(3000);

  // Clicar na aba Áudio.
  console.log("[STEP] Clicando na aba Áudio...");
  const audioTabBtn = await page.$('button:has-text("Áudio")');
  if (audioTabBtn) {
    await audioTabBtn.click();
    await page.waitForTimeout(1000);
  }

  // Verificar estado antes de iniciar.
  console.log("\n[STEP] Verificando estado ANTES de Iniciar...");
  const stateBefore = await page.evaluate(() => {
    // Tentar acessar o store via contexto global.
    const statusEl = document.querySelector('[data-testid="audio-capture-status"]');
    return {
      statusText: statusEl?.textContent || "N/A",
    };
  });
  console.log(`  Status antes: ${stateBefore.statusText}`);

  // Clicar em Iniciar.
  console.log("\n[STEP] Clicando em Iniciar...");
  const startBtn = await page.$('button:has-text("Iniciar")');
  if (startBtn) {
    const isDisabled = await startBtn.isDisabled();
    console.log(`  Botão disabled: ${isDisabled}`);
    if (!isDisabled) {
      await startBtn.click();
      console.log("  Clique realizado. Aguardando 3s...");
      await page.waitForTimeout(3000);
    }
  }

  // Verificar estado depois de iniciar.
  console.log("\n[STEP] Verificando estado DEPOIS de Iniciar...");
  const stateAfter = await page.evaluate(() => {
    const statusEl = document.querySelector('[data-testid="audio-capture-status"]');
    const rmsMeter = document.querySelector('[data-testid="rms-meter"]');
    return {
      statusText: statusEl?.textContent || "N/A",
      rmsMeterText: rmsMeter?.textContent || "N/A",
    };
  });
  console.log(`  Status depois: ${stateAfter.statusText}`);
  console.log(`  RMS meter: ${stateAfter.rmsMeterText}`);

  // Verificar eventos WebSocket.
  console.log(`\n[CHECK] WebSocket logs: ${wsLogs.length}`);
  for (const log of wsLogs) {
    console.log(`  ${log}`);
  }

  // Contar tipos de eventos.
  const eventTypes = {};
  for (const log of wsLogs) {
    if (log.startsWith("WS recv: ")) {
      const et = log.substring(9);
      eventTypes[et] = (eventTypes[et] || 0) + 1;
    }
  }
  console.log("\n[CHECK] Event types recebidos:");
  for (const [et, count] of Object.entries(eventTypes)) {
    console.log(`  ${et}: ${count}`);
  }

  // Verificar bridge logs.
  const bridgeLogs = consoleLogs.filter(l => l.includes("bridge") || l.includes("audio."));
  console.log(`\n[CHECK] Bridge/audio logs: ${bridgeLogs.length}`);
  for (const log of bridgeLogs) {
    console.log(`  ${log}`);
  }

  // Print ALL DIAG logs.
  const diagLogs = consoleLogs.filter(l => l.includes("DIAG"));
  console.log(`\n[CHECK] ALL DIAG logs: ${diagLogs.length}`);
  for (const log of diagLogs) {
    console.log(`  ${log}`);
  }

  // Print ALL console logs.
  console.log(`\n[CHECK] ALL console logs: ${consoleLogs.length}`);
  for (const log of consoleLogs) {
    console.log(`  ${log}`);
  }

  await page.screenshot({ path: "_diag_frontend2.png", fullPage: true });
  console.log("\n[STEP] Screenshot salvo em _diag_frontend2.png");

  await browser.close();
}

main().catch(console.error);
