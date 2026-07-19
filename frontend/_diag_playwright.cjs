// Diagnóstico Sprint 15.1 — testa frontend com Playwright.
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const consoleLogs = [];
  page.on("console", (msg) => {
    consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
  });

  const pageErrors = [];
  page.on("pageerror", (err) => {
    pageErrors.push(err.message);
  });

  const wsLogs = [];
  page.on("websocket", (ws) => {
    wsLogs.push(`WS opened: ${ws.url()}`);
    ws.on("framereceived", (frame) => {
      const text = typeof frame.payload === "string" ? frame.payload : JSON.stringify(frame.payload);
      if (text.includes("audio")) {
        wsLogs.push(`WS recv: ${text.substring(0, 200)}`);
      }
    });
    ws.on("framesent", (frame) => {
      wsLogs.push(`WS sent: ${frame.payload}`);
    });
    ws.on("close", () => wsLogs.push("WS closed"));
  });

  console.log("[STEP] Navegando para http://localhost:5173...");
  await page.goto("http://localhost:5173", { waitUntil: "networkidle", timeout: 15000 });

  await page.waitForTimeout(3000);

  console.log("[STEP] Página carregada. Verificando estado...");

  console.log(`\n[CHECK] Page errors: ${pageErrors.length}`);
  for (const e of pageErrors) {
    console.log(`  - ${e}`);
  }

  console.log(`\n[CHECK] Console logs (last 30): ${consoleLogs.length}`);
  for (const log of consoleLogs.slice(-30)) {
    console.log(`  ${log}`);
  }

  console.log(`\n[CHECK] WebSocket logs: ${wsLogs.length}`);
  for (const log of wsLogs) {
    console.log(`  ${log}`);
  }

  // Navegar para a página de configurações de áudio.
  console.log("\n[STEP] Navegando para /configuracoes...");
  try {
    await page.goto("http://localhost:5173/configuracoes", { waitUntil: "networkidle", timeout: 10000 });
    await page.waitForTimeout(2000);
    console.log("[STEP] Página de configurações carregada");

    // Clicar na aba Áudio.
    const audioTabBtn = await page.$('button:has-text("Áudio")');
    if (audioTabBtn) {
      await audioTabBtn.click();
      await page.waitForTimeout(1000);
      console.log("[STEP] Aba Áudio clicada");
    } else {
      console.log("[WARN] Botão aba Áudio não encontrado");
    }
  } catch (e) {
    console.log(`[WARN] Navegação falhou: ${e}`);
  }

  const audioStatus = await page.$('[data-testid="audio-capture-status"]');
  if (audioStatus) {
    const text = await audioStatus.textContent();
    console.log(`\n[CHECK] Audio capture status: ${text}`);
  } else {
    console.log("\n[CHECK] Audio capture status element not found");
  }

  console.log("\n[STEP] Procurando botão Iniciar...");
  const startBtn = await page.$('button:has-text("Iniciar")');
  if (startBtn) {
    const isDisabled = await startBtn.isDisabled();
    console.log(`[CHECK] Botão Iniciar encontrado. Disabled: ${isDisabled}`);
    if (!isDisabled) {
      console.log("[STEP] Clicando em Iniciar...");
      await startBtn.click();
      await page.waitForTimeout(3000);

      console.log(`\n[CHECK] WebSocket logs após Iniciar: ${wsLogs.length}`);
      for (const log of wsLogs.slice(-10)) {
        console.log(`  ${log}`);
      }

      const statusAfter = await page.$('[data-testid="audio-capture-status"]');
      if (statusAfter) {
        const text = await statusAfter.textContent();
        console.log(`[CHECK] Audio capture status após Iniciar: ${text}`);
      }

      // Verificar RMS meter.
      const rmsMeter = await page.$('[data-testid="rms-meter"]');
      if (rmsMeter) {
        const text = await rmsMeter.textContent();
        console.log(`[CHECK] RMS meter text: ${text}`);
      }
    }
  } else {
    console.log("[CHECK] Botão Iniciar não encontrado");
  }

  await page.screenshot({ path: "_diag_frontend.png", fullPage: true });
  console.log("\n[STEP] Screenshot salvo em _diag_frontend.png");

  console.log(`\n[FINAL] Total console logs: ${consoleLogs.length}`);
  console.log(`[FINAL] Total page errors: ${pageErrors.length}`);
  console.log(`[FINAL] Total WS logs: ${wsLogs.length}`);

  // Print all console logs for debugging.
  if (consoleLogs.length > 0) {
    console.log("\n[ALL CONSOLE LOGS]");
    for (const log of consoleLogs) {
      console.log(`  ${log}`);
    }
  }

  await browser.close();
}

main().catch(console.error);
