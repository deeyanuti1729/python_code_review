const sourceInput = document.querySelector("#source");
const modeInput = document.querySelector("#mode");
const reviewButton = document.querySelector("#review-button");
const runButton = document.querySelector("#run-button");
const reviewStatus = document.querySelector("#review-status");
const resultsPanel = document.querySelector("#results-panel");
const results = document.querySelector("#results");
const executionPanel = document.querySelector("#execution-panel");
const executionStatus = document.querySelector("#execution-status");
const executionOutput = document.querySelector("#execution-output");
const resultCount = document.querySelector("#result-count");
const characterCount = document.querySelector("#character-count");
const promptForm = document.querySelector("#prompt-form");
const promptTitle = document.querySelector("#prompt-title");
const promptText = document.querySelector("#prompt-text");
const promptList = document.querySelector("#prompt-list");
const promptStatus = document.querySelector("#prompt-status");
const exportDocxButton = document.querySelector("#export-docx");
const exportPdfButton = document.querySelector("#export-pdf");
const correctedCodeInput = document.querySelector("#corrected-code");
const correctedCodeCount = document.querySelector("#corrected-code-count");
const correctedCodeStatus = document.querySelector("#corrected-code-status");
const downloadCorrectedDocxButton = document.querySelector("#download-corrected-docx");
const downloadCorrectedPdfButton = document.querySelector("#download-corrected-pdf");
const promptStorageKey = "codecheck.savedPrompts";
const maxSourceLength = 1_000_000;
const maxRunSourceLength = 100_000;
let reviewRequestId = 0;
let runRequestId = 0;

const categories = [
  "Bugs & Logic",
  "Security",
  "Performance",
  "Maintainability",
  "Edge Cases",
];

function showStatus(element, message, isError = false) {
  element.textContent = message;
  element.classList.toggle("status-error", isError);
}

function addText(parent, tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  parent.append(element);
  return element;
}

function renderFinding(finding) {
  const card = document.createElement("article");
  card.className = "finding";
  const top = document.createElement("div");
  top.className = "finding-top";

  addText(top, "span", "tag", finding.category);
  const severityClass = `tag severity severity-${finding.severity.toLowerCase()}`;
  addText(top, "span", severityClass, finding.severity);
  if (finding.source) addText(top, "span", "tag finding-source", finding.source);
  addText(top, "span", "finding-line", `Line ${finding.line}`);
  card.append(top);
  addText(card, "p", "", finding.issue);
  const fix = document.createElement("p");
  fix.className = "fix";
  addText(fix, "strong", "", "Suggestion: ");
  fix.append(document.createTextNode(finding.fix));
  card.append(fix);
  return card;
}

function renderResults(report) {
  results.replaceChildren();
  const findingCount = report.findings.length;
  resultCount.textContent = `${findingCount} ${findingCount === 1 ? "finding" : "findings"}`;

  if (report.syntax_error) {
    const alert = document.createElement("div");
    alert.className = "syntax-alert";
    addText(alert, "strong", "", "Python syntax error");
    const location = report.syntax_error.line
      ? `Line ${report.syntax_error.line}${report.syntax_error.column ? `, column ${report.syntax_error.column}` : ""}: `
      : "";
    addText(alert, "code", "", `${location}${report.syntax_error.message}`);
    results.append(alert);
  }

  if (findingCount) {
    for (const finding of report.findings) results.append(renderFinding(finding));
  } else if (!report.syntax_error) {
    const clean = document.createElement("div");
    clean.className = "clean-report";
    addText(clean, "span", "clean-check", "✓");
    const copy = document.createElement("div");
    addText(copy, "strong", "", "No errors found");
    addText(copy, "p", "", "No syntax errors or heuristic issues were detected. This does not guarantee the code is error-free.");
    clean.append(copy);
    results.append(clean);
  }

  const categoriesSummary = document.createElement("div");
  categoriesSummary.className = "category-summary";
  for (const category of categories) {
    const count = report.findings.filter((finding) => finding.category === category).length;
    addText(categoriesSummary, "span", "category-count", `${category}: ${count}`);
  }
  results.append(categoriesSummary);
}

function mergeFindings(staticFindings, aiFindings) {
  const findings = [...staticFindings];
  const keys = new Set(
    findings.map((finding) =>
      `${finding.category}:${finding.line}:${finding.issue.trim().toLocaleLowerCase()}`,
    ),
  );
  for (const finding of aiFindings) {
    const key = `${finding.category}:${finding.line}:${finding.issue.trim().toLocaleLowerCase()}`;
    if (!keys.has(key)) {
      findings.push({ ...finding, source: "Gemini" });
      keys.add(key);
    }
  }
  return findings.sort((left, right) =>
    categories.indexOf(left.category) - categories.indexOf(right.category)
      || left.line - right.line
      || left.issue.localeCompare(right.issue),
  );
}

function resetResults() {
  results.replaceChildren();
  resultCount.textContent = "Ready when you are";

  const emptyState = document.createElement("div");
  emptyState.className = "empty-state";
  addText(emptyState, "span", "empty-icon", "⌁");
  addText(emptyState, "h3", "", "Your review will show up here");
  addText(
    emptyState,
    "p",
    "",
    "Run a check for static findings and Gemini's additional code review.",
  );
  results.append(emptyState);
}

async function reviewCode() {
  const source = sourceInput.value;
  if (!source.trim()) {
    showStatus(reviewStatus, "Paste Python code or a diff before starting a review.", true);
    sourceInput.focus();
    return;
  }
  if (source.length > maxSourceLength) {
    showStatus(reviewStatus, "Code is over the 1,000,000 character limit.", true);
    return;
  }

  const requestId = ++reviewRequestId;
  correctedCodeInput.value = "";
  correctedCodeCount.textContent = "0 / 1,000,000";
  showStatus(correctedCodeStatus, "");
  reviewButton.disabled = true;
  reviewButton.textContent = "Reviewing…";
  showStatus(reviewStatus, "");
  let localReviewComplete = false;
  try {
    const response = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, mode: modeInput.value }),
    });
    let report = await response.json();
    if (!response.ok) throw new Error(report.error || `Review failed (${response.status}).`);
    if (requestId !== reviewRequestId) return;
    renderResults(report);
    showStatus(reviewStatus, "Review complete.");
    localReviewComplete = true;
    resultsPanel.focus({ preventScroll: true });
    resultsPanel.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "start",
    });
    if (modeInput.value === "diff") {
      showStatus(correctedCodeStatus, "AI correction is available for Python snippets, not diffs.", true);
      return;
    }

    showStatus(correctedCodeStatus, "Sending code to Gemini for correction…");
    reviewButton.textContent = "Correcting…";
    const correctionResponse = await fetch("/api/correct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, findings: report.findings, syntax_error: report.syntax_error }),
    });
    const correction = await correctionResponse.json();
    if (!correctionResponse.ok) {
      throw new Error(correction.error || `Gemini correction failed (${correctionResponse.status}).`);
    }
    if (requestId !== reviewRequestId) return;
    if (sourceInput.value !== source) {
      showStatus(correctedCodeStatus, "The input changed while Gemini was working. Review the current code again.", true);
      return;
    }

    correctedCodeInput.value = correction.corrected_code;
    correctedCodeCount.textContent = `${correctedCodeInput.value.length.toLocaleString()} / 1,000,000`;
    report = {
      ...report,
      findings: mergeFindings(report.findings, correction.findings),
    };
    renderResults(report);
    showStatus(reviewStatus, "Static and Gemini reviews complete.");
    if (correction.syntax_error) {
      showStatus(
        correctedCodeStatus,
        `Gemini's correction still has a syntax error on line ${correction.syntax_error.line}: ${correction.syntax_error.message}. Please verify it.`,
        true,
      );
    } else {
      showStatus(correctedCodeStatus, "Gemini correction ready. Review it before using or running it.");
    }
    correctedCodeInput.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "center",
    });
  } catch (error) {
    if (requestId === reviewRequestId) {
      if (localReviewComplete) {
        showStatus(correctedCodeStatus, error.message || "Could not generate an AI correction.", true);
        showStatus(reviewStatus, "Local review complete; AI correction failed.", true);
      } else {
        showStatus(reviewStatus, error.message || "Could not reach the local review server.", true);
      }
    }
  } finally {
    if (requestId === reviewRequestId) {
      reviewButton.disabled = false;
      reviewButton.innerHTML = '<span aria-hidden="true">✦</span> Review code';
    }
  }
}

async function runCode() {
  const source = sourceInput.value;
  if (!source.trim()) {
    showStatus(reviewStatus, "Paste Python code before running it.", true);
    sourceInput.focus();
    return;
  }
  if (source.length > maxRunSourceLength) {
    showStatus(reviewStatus, "Code is over the 100,000 character run limit.", true);
    return;
  }

  const requestId = ++runRequestId;
  runButton.disabled = true;
  runButton.textContent = "Running…";
  executionPanel.hidden = false;
  executionStatus.classList.remove("failed");
  executionStatus.textContent = "Running locally…";
  executionOutput.textContent = "";
  showStatus(reviewStatus, "");

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `Code execution failed (${response.status}).`);
    if (requestId !== runRequestId) return;

    const output = [];
    if (result.stdout) output.push(result.stdout);
    if (result.stderr) {
      if (output.length) output.push("\n--- stderr ---\n");
      output.push(result.stderr);
    }
    if (result.timed_out) output.push("\nExecution stopped after the 5-second time limit.");
    if (result.truncated) output.push("\nOutput truncated at the 256 KB limit.");
    executionOutput.textContent = output.join("").trimEnd();

    const status = result.timed_out
      ? "Stopped: time limit reached"
      : result.truncated
        ? "Stopped: output limit reached"
        : `Finished with exit code ${result.exit_code}`;
    executionStatus.textContent = status;
    executionStatus.classList.toggle("failed", result.timed_out || result.exit_code !== 0);
    executionPanel.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "nearest",
    });
    executionPanel.focus({ preventScroll: true });
  } catch (error) {
    if (requestId === runRequestId) {
      executionStatus.textContent = "Could not run code";
      executionStatus.classList.add("failed");
      executionOutput.textContent = error.message || "Could not reach the local run service.";
      executionPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  } finally {
    if (requestId === runRequestId) {
      runButton.disabled = modeInput.value === "diff";
      runButton.textContent = "Run code";
    }
  }
}

async function copyText(text, label) {
  if (!text) {
    showStatus(reviewStatus, "There is nothing to copy yet.", true);
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    showStatus(reviewStatus, `${label} copied to clipboard.`);
  } catch {
    showStatus(reviewStatus, "Clipboard access was blocked. Select and copy the text manually.", true);
  }
}

function loadPrompts() {
  try {
    const saved = localStorage.getItem(promptStorageKey);
    if (saved === null) return [];
    const prompts = JSON.parse(saved);
    if (
      !Array.isArray(prompts)
      || prompts.some((item) => typeof item.id !== "string"
        || typeof item.title !== "string"
        || typeof item.text !== "string")
    ) {
      throw new Error("Saved prompt data has an unexpected format.");
    }
    return prompts;
  } catch (error) {
    showStatus(promptStatus, `Could not load saved prompts: ${error.message}`, true);
    return [];
  }
}

let savedPrompts = loadPrompts();

function persistPrompts() {
  try {
    localStorage.setItem(promptStorageKey, JSON.stringify(savedPrompts));
    showStatus(promptStatus, "Prompts saved in this browser.");
    return true;
  } catch (error) {
    showStatus(promptStatus, `Could not save prompts: ${error.message}`, true);
    return false;
  }
}

function renderPrompts() {
  promptList.replaceChildren();
  exportDocxButton.disabled = savedPrompts.length === 0;
  exportPdfButton.disabled = savedPrompts.length === 0;
  if (!savedPrompts.length) {
    addText(promptList, "div", "prompt-empty", "Your saved prompts will appear here.");
    return;
  }

  for (const prompt of savedPrompts) {
    const card = document.createElement("article");
    card.className = "saved-prompt";
    addText(card, "h3", "saved-prompt-title", prompt.title || "Untitled prompt");
    addText(card, "p", "saved-prompt-preview", prompt.text);
    const actions = document.createElement("div");
    actions.className = "saved-prompt-actions";

    const useButton = addText(actions, "button", "button button-quiet", "Edit");
    useButton.type = "button";
    useButton.addEventListener("click", () => {
      promptTitle.value = prompt.title;
      promptText.value = prompt.text;
      promptText.focus();
      showStatus(promptStatus, "Prompt loaded into the editor.");
    });

    const copyButton = addText(actions, "button", "button button-quiet", "Copy");
    copyButton.type = "button";
    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(prompt.text);
        showStatus(promptStatus, "Prompt copied to clipboard.");
      } catch {
        showStatus(promptStatus, "Clipboard access was blocked. Select and copy the prompt manually.", true);
      }
    });

    const deleteButton = addText(actions, "button", "button button-quiet delete-prompt", "Delete");
    deleteButton.type = "button";
    deleteButton.addEventListener("click", () => {
      const previous = savedPrompts;
      savedPrompts = savedPrompts.filter((item) => item.id !== prompt.id);
      if (persistPrompts()) renderPrompts();
      else savedPrompts = previous;
    });

    card.append(actions);
    promptList.append(card);
  }
}

async function copyCorrectedCode() {
  const source = correctedCodeInput.value;
  if (!source) {
    showStatus(correctedCodeStatus, "Paste corrected code before copying.", true);
    correctedCodeInput.focus();
    return;
  }
  try {
    await navigator.clipboard.writeText(source);
    showStatus(correctedCodeStatus, "Corrected code copied to clipboard.");
  } catch {
    showStatus(correctedCodeStatus, "Clipboard access was blocked. Select and copy the code manually.", true);
  }
}

async function downloadCorrectedCodeDocx() {
  const source = correctedCodeInput.value;
  if (!source.trim()) {
    showStatus(correctedCodeStatus, "Paste corrected code before downloading.", true);
    correctedCodeInput.focus();
    return;
  }
  if (source.length > maxSourceLength) {
    showStatus(correctedCodeStatus, "Code is over the 1,000,000 character export limit.", true);
    return;
  }

  downloadCorrectedDocxButton.disabled = true;
  showStatus(correctedCodeStatus, "Preparing your DOCX…");
  try {
    const response = await fetch("/api/export/code-docx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || `DOCX export failed (${response.status}).`);
    }

    const file = await response.blob();
    const url = URL.createObjectURL(file);
    const download = document.createElement("a");
    download.href = url;
    download.download = "corrected-code.docx";
    document.body.append(download);
    download.click();
    download.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showStatus(correctedCodeStatus, "Corrected code DOCX downloaded.");
  } catch (error) {
    showStatus(correctedCodeStatus, `Could not export DOCX: ${error.message}`, true);
  } finally {
    downloadCorrectedDocxButton.disabled = false;
  }
}

function downloadCorrectedCodePdf() {
  const source = correctedCodeInput.value;
  if (!source.trim()) {
    showStatus(correctedCodeStatus, "Paste corrected code before printing.", true);
    correctedCodeInput.focus();
    return;
  }

  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    showStatus(correctedCodeStatus, "Allow pop-ups to print or save your code as PDF.", true);
    return;
  }

  const printDocument = printWindow.document;
  printDocument.open();
  printDocument.write("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Corrected code</title></head><body></body></html>");
  printDocument.close();
  const style = printDocument.createElement("style");
  style.textContent = `
    body { margin: 32px; color: #172033; font: 12px/1.5 Consolas, "Courier New", monospace; }
    h1 { margin: 0 0 20px; font: 600 20px/1.3 Arial, sans-serif; }
    pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; tab-size: 4; }
    @page { margin: 18mm; }
    @media print { body { margin: 0; } }
  `;
  printDocument.head.append(style);
  const heading = printDocument.createElement("h1");
  heading.textContent = "Corrected code";
  const code = printDocument.createElement("pre");
  code.textContent = source;
  printDocument.body.append(heading, code);

  showStatus(correctedCodeStatus, "Print dialog opened. Choose “Save as PDF” to create a PDF file.");
  printWindow.focus();
  printWindow.setTimeout(() => printWindow.print(), 250);
}

async function exportPromptsAsDocx() {
  if (!savedPrompts.length) return;
  exportDocxButton.disabled = true;
  showStatus(promptStatus, "Preparing your DOCX…");
  try {
    const response = await fetch("/api/export/docx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompts: savedPrompts }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || `DOCX export failed (${response.status}).`);
    }

    const file = await response.blob();
    const url = URL.createObjectURL(file);
    const download = document.createElement("a");
    download.href = url;
    download.download = "saved-prompts.docx";
    document.body.append(download);
    download.click();
    download.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showStatus(promptStatus, "DOCX downloaded.");
  } catch (error) {
    showStatus(promptStatus, `Could not export DOCX: ${error.message}`, true);
  } finally {
    exportDocxButton.disabled = savedPrompts.length === 0;
  }
}

function exportPromptsAsPdf() {
  if (!savedPrompts.length) return;
  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    showStatus(promptStatus, "Allow pop-ups to print or save your prompts as PDF.", true);
    return;
  }

  const printDocument = printWindow.document;
  printDocument.open();
  printDocument.write("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Saved prompts</title></head><body></body></html>");
  printDocument.close();
  const style = printDocument.createElement("style");
  style.textContent = `
    body { max-width: 760px; margin: 48px auto; padding: 0 24px; color: #172033; font: 14px/1.65 Arial, sans-serif; }
    h1 { margin-bottom: 8px; font-size: 26px; }
    .intro { margin: 0 0 28px; color: #596579; }
    section { margin: 0 0 26px; break-inside: avoid; }
    h2 { margin: 0 0 8px; padding-bottom: 5px; border-bottom: 1px solid #d5dbe5; font-size: 17px; }
    p { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
    @media print { body { margin: 0 auto; padding: 0; } }
  `;
  printDocument.head.append(style);
  const heading = printDocument.createElement("h1");
  heading.textContent = "Saved prompts";
  printDocument.body.append(heading);
  const intro = printDocument.createElement("p");
  intro.className = "intro";
  intro.textContent = "Prompts exported from Codecheck.";
  printDocument.body.append(intro);

  for (const [index, prompt] of savedPrompts.entries()) {
    const section = printDocument.createElement("section");
    const title = printDocument.createElement("h2");
    title.textContent = prompt.title || `Prompt ${index + 1}`;
    const text = printDocument.createElement("p");
    text.textContent = prompt.text;
    section.append(title, text);
    printDocument.body.append(section);
  }

  showStatus(promptStatus, "Print dialog opened. Choose “Save as PDF” to create a PDF file.");
  printWindow.focus();
  printWindow.setTimeout(() => printWindow.print(), 250);
}

sourceInput.addEventListener("input", () => {
  characterCount.textContent = `${sourceInput.value.length.toLocaleString()} / 1,000,000`;
  if (!reviewButton.disabled) {
    correctedCodeInput.value = "";
    correctedCodeCount.textContent = "0 / 1,000,000";
    showStatus(correctedCodeStatus, "");
  }
  if (!executionPanel.hidden) {
    runRequestId += 1;
    executionPanel.hidden = true;
    runButton.disabled = modeInput.value === "diff";
    runButton.textContent = "Run code";
  }
});
correctedCodeInput.addEventListener("input", () => {
  correctedCodeCount.textContent = `${correctedCodeInput.value.length.toLocaleString()} / 1,000,000`;
});
document.querySelector("#copy-corrected-code").addEventListener("click", copyCorrectedCode);
downloadCorrectedDocxButton.addEventListener("click", downloadCorrectedCodeDocx);
downloadCorrectedPdfButton.addEventListener("click", downloadCorrectedCodePdf);
reviewButton.addEventListener("click", reviewCode);
runButton.addEventListener("click", runCode);
modeInput.addEventListener("change", () => {
  runButton.disabled = modeInput.value === "diff";
  if (modeInput.value === "diff") {
    showStatus(reviewStatus, "Run code is available for Python snippets, not unified diffs.");
  }
});
document.querySelector("#clear-code").addEventListener("click", () => {
  reviewRequestId += 1;
  runRequestId += 1;
  sourceInput.value = "";
  characterCount.textContent = "0 / 1,000,000";
  correctedCodeInput.value = "";
  correctedCodeCount.textContent = "0 / 1,000,000";
  showStatus(correctedCodeStatus, "");
  reviewButton.disabled = false;
  reviewButton.innerHTML = '<span aria-hidden="true">✦</span> Review code';
  runButton.disabled = modeInput.value === "diff";
  runButton.textContent = "Run code";
  executionPanel.hidden = true;
  showStatus(reviewStatus, "");
  resetResults();
  sourceInput.focus();
});
document.querySelector("#copy-code").addEventListener("click", () => copyText(sourceInput.value, "Code"));
sourceInput.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") reviewCode();
});
exportDocxButton.addEventListener("click", exportPromptsAsDocx);
exportPdfButton.addEventListener("click", exportPromptsAsPdf);

promptForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = promptText.value.trim();
  if (!text) {
    showStatus(promptStatus, "Enter prompt text before saving.", true);
    promptText.focus();
    return;
  }

  const prompt = {
    id: crypto.randomUUID(),
    title: promptTitle.value.trim() || "Untitled prompt",
    text,
  };
  const previous = savedPrompts;
  savedPrompts = [prompt, ...savedPrompts];
  if (persistPrompts()) {
    promptTitle.value = "";
    promptText.value = "";
    renderPrompts();
  } else {
    savedPrompts = previous;
  }
});

renderPrompts();
