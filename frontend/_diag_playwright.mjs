// Diagnóstico Sprint 15.1 — testa frontend com Playwright.
// Verifica se a página carrega, se WebSocket conecta, e se eventos audio.level chegam.

import { chromium } from "playwright";

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  // Captura logs do console.
  const consoleLogs: string[] = [];
  page.on("console", (msg) => {
    consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
  });

  // Captura erros de página.
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => {
    pageErrors.push(err.message);
  });

  // Captura requisições WebSocket.
  const wsLogs: string[] = [];
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

  // Aguarda um pouco para a página carregar.
  await page.waitForTimeout(3000);

  console.log("[STEP] Página carregada. Verificando estado...");

  // Verifica se há erros de página.
  console.log(`\n[CHECK] Page errors: ${pageErrors.length}`);
  for (const e of pageErrors) {
    console.log(`  - ${e}`);
  }

  // Verifica logs do console.
  console.log(`\n[CHECK] Console logs: ${consoleLogs.length}`);
  for (const log of consoleLogs.slice(-20)) {
    console.log(`  ${log}`);
  }

  // Verifica WebSocket.
  console.log(`\n[CHECK] WebSocket logs: ${wsLogs.length}`);
  for (const log of wsLogs) {
    console.log(`  ${log}`);
  }

  // Navegar para a página de configurações de áudio.
  console.log("\n[STEP] Navegando para Settings > Audio...");
  try {
    // Procurar por um link ou botão de Settings.
    const settingsLink = await page.$('a[href*="settings"], button:has-text("Settings"), button:has-text("Configurações")');
    if (settingsLink) {
      await settingsLink.click();
      await page.waitForTimeout(1000);
    }

    // Procurar por tab de Áudio.
    const audioTab = await page.$('button:has-text("Áudio"), [data-testid="audio-tab"], button:has-text("Audio")');
    if (audioTab) {
      await audioTab.click();
      await page.waitForTimeout(1000);
    }
  } catch (e) {
    console.log(`[WARN] Navegação falhou: ${e}`);
  }

  // Verificar estado do AudioTab.
  const audioStatus = await page.$('[data-testid="audio-capture-status"]');
  if (audioStatus) {
    const text = await audioStatus.textContent();
    console.log(`\n[CHECK] Audio capture status: ${text}`);
  } else {
    console.log("\n[CHECK] Audio capture status element not found");
  }

  // Clicar em "Iniciar" se possível.
  console.log("\n[STEP] Procurando botão Iniciar...");
  const startBtn = await page.$('button:has-text("Iniciar")');
  if (startBtn) {
    const isDisabled = await startBtn.isDisabled();
    console.log(`[CHECK] Botão Iniciar encontrado. Disabled: ${isDisabled}`);
    if (!isDisabled) {
      console.log("[STEP] Clicando em Iniciar...");
      await startBtn.click();
      await page.waitForTimeout(3000);

      // Verificar eventos WebSocket após clicar.
      console.log(`\n[CHECK] WebSocket logs após Iniciar: ${wsLogs.length}`);
      for (const log of wsLogs.slice(-10)) {
        console.log(`  ${log}`);
      }

      // Verificar estado do audio.
      const statusAfter = await page.$('[data-testid="audio-capture-status"]');
      if (statusAfter) {
        const text = await statusAfter.textContent();
        console.log(`[CHECK] Audio capture status após Iniciar: ${text}`);
      }
    }
  } else {
    console.log("[CHECK] Botão Iniciar não encontrado");
  }

  // Screenshot para debug.
  await page.screenshot({ path: "_diag_frontend.png", fullPage: true });
  console.log("\n[STEP] Screenshot salvo em _diag_frontend.png");

  // Logs finais.
  console.log(`\n[FINAL] Total console logs: ${consoleLogs.length}`);
  console.log(`[FINAL] Total page errors: ${pageErrors.length}`);
  console.log(`[FINAL] Total WS logs: ${wsLogs.length}`);

  await browser.close();
}

main().catch(console.error);
