const base = document.body.dataset.base;
const dialog = document.querySelector("#search-dialog");
const input = document.querySelector("#search-input");
const results = document.querySelector("#search-results");
const status = document.querySelector("#search-status");
let indexPromise;
let searchGeneration = 0;
function openSearch() {
  dialog.showModal();
  input.focus();
}
document
  .querySelectorAll(".search-trigger")
  .forEach((button) => button.addEventListener("click", openSearch));
document
  .querySelector("#close-search")
  .addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  const rect = dialog.getBoundingClientRect();
  if (
    event.target === dialog &&
    (event.clientX < rect.left ||
      event.clientX > rect.right ||
      event.clientY < rect.top ||
      event.clientY > rect.bottom)
  )
    dialog.close();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && dialog.open) {
    event.preventDefault();
    dialog.close();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (dialog.open) dialog.close();
    else openSearch();
  }
});
input.addEventListener("input", async () => {
  const generation = ++searchGeneration;
  const query = input.value.trim().toLowerCase();
  results.replaceChildren();
  if (!query) {
    status.textContent =
      "Type to search the guides. Use Tab to browse results.";
    return;
  }
  status.textContent = "Searching…";
  try {
    indexPromise ||= fetch(`${base}assets/search.json`)
      .then((response) => {
        if (!response.ok) throw new Error("Search unavailable");
        return response.json();
      })
      .catch((error) => {
        indexPromise = undefined;
        throw error;
      });
    const index = await indexPromise;
    if (generation !== searchGeneration) return;
    const words = query.split(/\s+/);
    const matches = index
      .map((page) => ({
        ...page,
        score: words.reduce(
          (sum, word) =>
            sum +
            (page.title.toLowerCase().includes(word) ? 10 : 0) +
            (page.text.toLowerCase().includes(word) ? 1 : 0),
          0,
        ),
      }))
      .filter((page) =>
        words.every((word) =>
          `${page.title} ${page.text}`.toLowerCase().includes(word),
        ),
      )
      .sort((a, b) => b.score - a.score)
      .slice(0, 12);
    status.textContent = matches.length
      ? `${matches.length} matching guides. Use Tab to browse results.`
      : "No matching guides. Try a component name or a shorter phrase.";
    for (const page of matches) {
      const link = document.createElement("a");
      link.href = page.url;
      const title = document.createElement("strong");
      title.textContent = page.title;
      const summary = document.createElement("span");
      const start = Math.max(0, page.text.toLowerCase().indexOf(words[0]) - 45);
      summary.textContent =
        (start ? "…" : "") + page.text.slice(start, start + 165) + "…";
      link.append(title, summary);
      results.append(link);
    }
  } catch {
    if (generation === searchGeneration)
      status.textContent =
        "Search could not load. The documentation navigation is still available.";
  }
});
const menuButton = document.querySelector(".menu-toggle");
const menu = document.querySelector("#mobile-nav");
menuButton.addEventListener("click", () => {
  const expanded = menuButton.getAttribute("aria-expanded") === "true";
  menuButton.setAttribute("aria-expanded", String(!expanded));
  menu.hidden = expanded;
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !menu.hidden) {
    menu.hidden = true;
    menuButton.setAttribute("aria-expanded", "false");
    menuButton.focus();
  }
});
document.querySelector(".theme-toggle").addEventListener("click", () => {
  const theme =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("ca-theme", theme);
  } catch {
    /* Theme still works when storage is disabled. */
  }
  renderDiagrams();
});
document.querySelectorAll(".copy-code").forEach((button) =>
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(
        button.closest(".code-block").querySelector("code").textContent,
      );
      button.textContent = "Copied";
    } catch {
      button.textContent = "Select code to copy";
    }
    setTimeout(() => {
      button.textContent = "Copy";
    }, 2200);
  }),
);
const phases = [
  [0, 0, "0 · Ready for a token"],
  [1, 0, "1 · Request asserted"],
  [1, 1, "2 · Token acknowledged"],
  [0, 1, "3 · Request returned"],
];
let phase = 0;
document.querySelector("#step-handshake")?.addEventListener("click", () => {
  phase = (phase + 1) % phases.length;
  document.querySelector("#request-bit").textContent = phases[phase][0];
  document.querySelector("#ack-bit").textContent = phases[phase][1];
  document.querySelector("#phase-label").textContent = phases[phase][2];
});
const diagrams = [...document.querySelectorAll(".mermaid")].map((element) => ({
  element,
  source: element.textContent,
}));
let diagramGeneration = 0;
async function renderDiagrams() {
  if (!diagrams.length) return;
  const generation = ++diagramGeneration;
  try {
    const { default: mermaid } = await import("mermaid");
    if (generation !== diagramGeneration) return;
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme:
        document.documentElement.dataset.theme === "dark" ? "dark" : "neutral",
      fontFamily: "Inter, sans-serif",
    });
    for (const [i, { element, source }] of diagrams.entries()) {
      const { svg } = await mermaid.render(
        `diagram-${generation}-${i}`,
        source,
      );
      if (generation !== diagramGeneration) return;
      element.innerHTML = svg;
    }
  } catch {
    /* Keep readable source when diagram rendering is unavailable. */
  }
}
renderDiagrams();
