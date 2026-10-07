// Decorative metal routing and standard-cell rows, not a circuit schematic.
export function circuitArtwork() {
  const routes = [
    "M0 46 H686 L726 86 H1004 L1044 126 V214 H1104",
    "M0 62 H678 L718 102 H996 L1028 134 V230 H1104",
    "M0 78 H670 L710 118 H980 L1012 150 V246 H1104",
    "M1440 38 H1254 L1214 78 V190",
    "M1440 54 H1270 L1230 94 V190",
    "M1440 70 H1286 L1246 110 V190",
    "M1440 246 H1280",
    "M1440 262 H1280",
    "M1440 278 H1280",
    "M1440 462 H1364 L1324 422 V326 H1280",
    "M1440 478 H1348 L1308 438 V342 H1280",
    "M1440 566 H1032 L992 526 V418 L1032 378 H1136 V366",
    "M1440 582 H1016 L976 542 V402 L1028 350 H1104",
    "M0 566 H606 L654 518 H868 L916 470 V350 H1104",
    "M0 582 H614 L662 534 H884 L932 486 V334 H1104",
    "M0 598 H622 L670 550 H900 L948 502 V318 H1104",
    "M1168 366 V446 L1216 494 H1440",
    "M1184 366 V430 L1232 478 H1440",
    "M1200 366 V414 L1248 462 H1300",
    "M1072 0 V78 L1168 174 V190",
    "M1088 0 V62 L1184 158 V190",
    "M1104 0 V46 L1200 142 V190",
  ];
  const pulses = [0, 3, 7, 9, 11, 13, 16, 20];
  const cells = Array.from({ length: 8 }, (_, row) =>
    Array.from(
      { length: 5 },
      (_, col) =>
        `<rect class="silicon-cell${(row + col) % 5 === 0 ? " silicon-cell-active" : ""}" x="${1128 + col * 26}" y="${213 + row * 17}" width="${col % 2 ? 18 : 21}" height="10"/>`,
    ).join(""),
  ).join("");
  return `<svg class="circuit-art" viewBox="0 0 1440 640" preserveAspectRatio="xMaxYMid slice" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="circuit-visibility"><stop offset="0" stop-color="white" stop-opacity=".18"/><stop offset=".48" stop-color="white" stop-opacity=".32"/><stop offset=".77" stop-color="white" stop-opacity=".9"/><stop offset="1" stop-color="white"/></linearGradient>
      <mask id="circuit-mask"><rect width="1440" height="640" fill="url(#circuit-visibility)"/></mask>
      <pattern id="silicon-vias" width="16" height="16" patternUnits="userSpaceOnUse"><rect x="6" y="6" width="2" height="2" rx=".4" fill="currentColor"/></pattern>
    </defs>
    <g mask="url(#circuit-mask)">
      <path class="silicon-boundary" d="M958 -30 H1398 V620 H846 V580 M974 -30 V148 L990 164 V286 M1398 602 H1010"/>
      <rect class="silicon-vias" x="970" y="16" width="446" height="582" fill="url(#silicon-vias)"/>
      <g class="circuit-traces">${routes.map((d) => `<path d="${d}"/>`).join("")}</g>
      <g class="silicon-die"><rect x="1088" y="174" width="208" height="208" rx="5"/><rect x="1104" y="190" width="176" height="176" rx="2"/><path d="M1116 202 H1268 V354 H1116 Z"/></g>
      <g class="silicon-cells">${cells}</g>
      <g class="circuit-vias">${[
        [686, 46],
        [678, 62],
        [670, 78],
        [868, 518],
        [884, 534],
        [900, 550],
        [1032, 566],
        [1016, 582],
        [1300, 462],
      ]
        .map(
          ([x, y]) =>
            `<rect x="${x - 3}" y="${y - 3}" width="6" height="6" rx="1"/>`,
        )
        .join("")}</g>
      <g class="circuit-pulses">${pulses.map((index) => `<path class="circuit-pulse" d="${routes[index]}" pathLength="1" stroke-dasharray=".045 1.1" stroke-dashoffset=".05"/>`).join("")}</g>
    </g>
  </svg><button class="circuit-toggle" type="button" aria-label="Pause circuit animation" aria-pressed="false" hidden><span aria-hidden="true">Ⅱ</span><span>Pause animation</span></button>`;
}
