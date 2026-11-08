(function (root) {
  "use strict";

  // La pagina legge i percorsi ottimi prodotti da Python e aggiorna soltanto
  // il confronto economico; l'algoritmo di ottimizzazione non è duplicato qui.
  function baselineParameters(instance) {
    return {
      largeFixed: instance.vehicles.large.fixed_cost_eur,
      smallFixed: instance.vehicles.small.fixed_cost_eur,
      largeKm: instance.vehicles.large.variable_cost_eur_km,
      smallKm: instance.vehicles.small.variable_cost_eur_km,
      wage: instance.operations.driver_eur_hour,
    };
  }

  function economicModel(results, parameters) {
    const one = results.scenarios.single_vehicle.totals;
    const two = results.scenarios.two_vehicles.totals;
    // Stesse conversioni di planner.py: decimetri -> km, decimi di s -> ore.
    const distanceOne = one.distance_dm / 10000;
    const distanceTwo = two.distance_dm / 10000;
    const hoursOne = one.driver_ds / 36000;
    const hoursTwo = two.driver_ds / 36000;
    const single = {
      fixed: parameters.largeFixed * one.vehicle_count,
      distance: distanceOne * parameters.largeKm,
      driver: hoursOne * parameters.wage,
    };
    const double = {
      fixed: parameters.smallFixed * two.vehicle_count,
      distance: distanceTwo * parameters.smallKm,
      driver: hoursTwo * parameters.wage,
    };
    single.total = single.fixed + single.distance + single.driver;
    double.total = double.fixed + double.distance + double.driver;
    return {
      single, double, distanceOne, distanceTwo, hoursOne, hoursTwo,
      threshold: double.total - single.distance - single.driver,
      difference: double.total - single.total,
    };
  }

  function chartInterval(baseMin, baseMax, threshold, selected) {
    const padding = Math.max(10, (baseMax - baseMin) * 0.12);
    let minimum = Math.min(baseMin, Math.floor(selected / 10) * 10);
    let maximum = Math.max(baseMax, Math.ceil(selected / 10) * 10);
    if (threshold >= 0 && threshold < minimum) {
      minimum = Math.max(0, Math.floor((threshold - padding) / 10) * 10);
    }
    if (threshold > maximum) {
      maximum = Math.ceil((threshold + padding) / 10) * 10;
    }
    if (maximum <= minimum) maximum = minimum + 10;
    return { minimum, maximum, containsThreshold: threshold >= minimum && threshold <= maximum };
  }

  const api = { baselineParameters, economicModel, chartInterval };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;

  const $ = (id) => document.getElementById(id);
  const number = (value, digits = 2) => new Intl.NumberFormat("it-IT", {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(value);
  const currency = (value, digits = 2) => new Intl.NumberFormat("it-IT", {
    style: "currency", currency: "EUR", minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(value);
  const integer = (value) => number(value, 0);
  const escape = (value) => String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
  const theme = getComputedStyle(document.documentElement);
  const colors = {
    green: theme.getPropertyValue("--green").trim() || "#315d46",
    copper: theme.getPropertyValue("--copper").trim() || "#a65f39",
    teal: theme.getPropertyValue("--teal").trim() || "#376e7a",
    ink: theme.getPropertyValue("--ink").trim() || "#233e34",
  };

  function text(id, value) { $(id).textContent = value; }
  function metric(id, value, unit) {
    $(id).innerHTML = `${escape(value)}<span class="unit">${escape(unit)}</span>`;
  }
  function roundedDuration(seconds) {
    const minutes = Math.round(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return hours ? `${hours} h ${rest.toString().padStart(2, "0")} min` : `${minutes} min`;
  }

  function graphMarkup(scenario, nodes, prefix) {
    // I nodi seguono l'ordine dei giri lungo un esagono schematico.
    // Queste posizioni servono alla leggibilità e non sono coordinate GPS.
    const slots = [
      { x: 320, y: 100, lx: 320, ly: 24, anchor: "middle" },
      { x: 450, y: 185, lx: 480, ly: 174, anchor: "start" },
      { x: 450, y: 355, lx: 480, ly: 344, anchor: "start" },
      { x: 320, y: 440, lx: 320, ly: 476, anchor: "middle" },
      { x: 190, y: 355, lx: 160, ly: 344, anchor: "end" },
      { x: 190, y: 185, lx: 160, ly: 174, anchor: "end" },
    ];
    const depot = nodes.find((node) => node.id === 0);
    const orderedIds = [depot.id, ...scenario.routes.flatMap((route) => route.node_ids.slice(1, -1))];
    const positions = Object.fromEntries(orderedIds.map((id, index) => [id, slots[index]]));
    function nameLines(name) {
      const lines = [];
      String(name).split(/\s+/).forEach((word) => {
        const last = lines.length - 1;
        if (last >= 0 && `${lines[last]} ${word}`.length <= 14) lines[last] += ` ${word}`;
        else lines.push(word);
      });
      return lines;
    }
    const routeColors = scenario.routes.length === 1 ? [colors.green] : [colors.copper, colors.teal];
    const routeWords = scenario.routes.map((route, index) => `Veicolo ${index + 1}: ${route.node_names.join(", ")}; carico ${route.load_kg} kg; ${number(route.distance_km, 4)} km.`).join(" ");
    const markers = routeColors.map((color, index) => `<marker id="${prefix}-arrow-${index}" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="5.3" markerHeight="5.3" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${color}"/></marker>`).join("");
    let paths = "";
    let labels = "";
    scenario.routes.forEach((route, index) => {
      route.arcs.forEach((arc) => {
        const a = positions[arc.from_id];
        const b = positions[arc.to_id];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const length = Math.hypot(dx, dy);
        const ux = dx / length;
        const uy = dy / length;
        const bend = 6;
        const sx = a.x + ux * 23;
        const sy = a.y + uy * 23;
        const ex = b.x - ux * 24;
        const ey = b.y - uy * 24;
        const cx = (sx + ex) / 2 - uy * bend;
        const cy = (sy + ey) / 2 + ux * bend;
        const labelX = (sx + ex) / 2 - uy * 14;
        const labelY = (sy + ey) / 2 + ux * 14;
        const dash = index === 1 ? ' stroke-dasharray="7 4"' : "";
        paths += `<path class="route-edge" d="M${sx},${sy} Q${cx},${cy} ${ex},${ey}" stroke="${routeColors[index]}" marker-end="url(#${prefix}-arrow-${index})"${dash}><title>${escape(arc.from_name)} → ${escape(arc.to_name)}: ${number(arc.distance_km, 4)} km</title></path>`;
        labels += `<text class="edge-label" x="${labelX}" y="${labelY}">${number(arc.distance_km)}</text>`;
      });
    });
    const nodeMarkup = nodes.map((node) => {
      const p = positions[node.id];
      const routeIndex = scenario.routes.findIndex((route) => route.node_ids.includes(node.id));
      const color = node.id === 0 ? colors.ink : routeColors[Math.max(routeIndex, 0)];
      const shape = node.id === 0
        ? `<rect x="${p.x - 20}" y="${p.y - 20}" width="40" height="40" rx="9" fill="${color}"/>`
        : `<circle cx="${p.x}" cy="${p.y}" r="18" fill="${color}"/>`;
      const lines = nameLines(node.name);
      const nameMarkup = lines.map((line, index) => `<tspan x="${p.lx}" y="${p.ly + index * 20}">${escape(line)}</tspan>`).join("");
      return `<g>${shape}<text class="node-id" x="${p.x}" y="${p.y}">${node.id}</text><text class="node-label" text-anchor="${p.anchor}">${nameMarkup}</text><text class="node-demand" x="${p.lx}" y="${p.ly + lines.length * 20}" text-anchor="${p.anchor}">${node.id === depot.id ? "Deposito" : `${integer(node.demand_kg)} kg`}</text></g>`;
    }).join("");
    return `<svg viewBox="0 0 640 550" role="img" aria-labelledby="${prefix}-title ${prefix}-desc"><title id="${prefix}-title">Grafo orientato, ${escape(scenario.label)}</title><desc id="${prefix}-desc">${escape(routeWords)} Il nodo ${depot.id} è il deposito di ${escape(depot.name)}. Le frecce indicano il verso del percorso; le etichette degli archi sono in chilometri. I nodi seguono l'ordine di visita, senza rappresentare la posizione geografica.</desc><defs>${markers}</defs>${paths}${labels}${nodeMarkup}</svg>`;
  }

  function routeDetails(scenario, nodes) {
    const routeColors = scenario.routes.length === 1 ? ["green"] : ["copper", "teal"];
    return scenario.routes.map((route, index) => {
      const routeLine = route.node_ids.map((id) => `<span>${escape(nodes[id].name)}</span>`).join('<span class="arrow" aria-hidden="true">→</span><span class="sr-only"> poi </span>');
      const arcRows = route.arcs.map((arc) => `<li>${escape(arc.from_name)} → ${escape(arc.to_name)}: ${number(arc.distance_km, 4)} km, ${number(arc.driving_seconds / 60)} min di guida</li>`).join("");
      return `<section class="route-detail"><div class="route-detail-heading"><h4><i class="dot ${routeColors[index]}" aria-hidden="true"></i>Veicolo ${index + 1}</h4><span class="load-pill">${integer(route.load_kg)} / ${integer(scenario.vehicle_parameters.capacity_kg)} kg</span></div><p class="route-line">${routeLine}</p><div class="route-mini-metrics"><span><strong>${number(route.distance_km, 4)} km</strong></span><span><strong>${number(route.total_minutes)} min</strong> complessivi</span><span>Carico <strong>${number(route.load_kg / scenario.vehicle_parameters.capacity_kg * 100, 1)}%</strong></span></div><details class="route-arc-details"><summary>Tratte e composizione del tempo</summary><ol>${arcRows}</ol><p>Guida ${number(route.driving_minutes)} min + servizio ${number(route.service_seconds / 60, 0)} min + preparazione ${number(route.preparation_seconds / 60, 0)} min = ${number(route.total_minutes)} min.</p></details></section>`;
    }).join("");
  }

  function niceStep(raw) {
    const magnitude = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 0.01))));
    const fraction = raw / magnitude;
    return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10) * magnitude;
  }

  function drawCostChart(model, parameters, interval) {
    const target = $("cost-chart");
    const width = Math.max(300, Math.round(target.getBoundingClientRect().width || 760));
    const height = width < 500 ? 320 : 355;
    const margin = { left: width < 500 ? 51 : 58, right: 20, top: 39, bottom: 56 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const intercept = model.single.distance + model.single.driver;
    const ymaxValue = Math.max(interval.maximum + intercept, model.double.total, 1) * 1.08;
    const yStep = niceStep(ymaxValue / 5);
    const ymax = Math.ceil(ymaxValue / yStep) * yStep;
    const x = (value) => margin.left + (value - interval.minimum) / (interval.maximum - interval.minimum) * plotWidth;
    const y = (value) => margin.top + plotHeight - value / ymax * plotHeight;
    const bottom = height - margin.bottom;
    let grid = "";
    for (let value = 0; value <= ymax + yStep / 100; value += yStep) {
      grid += `<line x1="${margin.left}" y1="${y(value)}" x2="${width - margin.right}" y2="${y(value)}" stroke="#d1dac7" stroke-width="1"/><text class="tick-label" x="${margin.left - 9}" y="${y(value) + 4}" text-anchor="end">${number(value, 0)}</text>`;
    }
    const xTickCount = width < 500 ? 3 : 4;
    for (let i = 0; i <= xTickCount; i += 1) {
      const value = interval.minimum + (interval.maximum - interval.minimum) * i / xTickCount;
      grid += `<line x1="${x(value)}" y1="${bottom}" x2="${x(value)}" y2="${bottom + 4}" stroke="#929f84"/><text class="tick-label" x="${x(value)}" y="${bottom + 20}" text-anchor="middle">${number(value, 0)}</text>`;
    }
    let threshold = "";
    if (interval.containsThreshold) {
      const tx = x(model.threshold);
      const labelWidth = Math.min(145, width - margin.left - margin.right);
      const labelX = Math.max(margin.left + labelWidth / 2, Math.min(width - margin.right - labelWidth / 2, tx));
      threshold = `<line x1="${tx}" y1="${margin.top + 3}" x2="${tx}" y2="${bottom}" stroke="#74836a" stroke-dasharray="4 4" stroke-width="1.2"/><rect x="${labelX - labelWidth / 2}" y="8" width="${labelWidth}" height="24" rx="6" fill="#f7f5ed"/><text class="threshold-label" x="${labelX}" y="24" text-anchor="middle">Pareggio ${escape(currency(model.threshold))}</text><circle cx="${tx}" cy="${y(model.double.total)}" r="5" fill="#eaf0e5" stroke="#233e34" stroke-width="1.5"/>`;
    }
    const selectedX = x(parameters.largeFixed);
    const chartDesc = `Noleggio del veicolo grande da ${number(interval.minimum, 0)} a ${number(interval.maximum, 0)} euro per giornata. Il costo di un veicolo cresce da ${currency(interval.minimum + intercept)} a ${currency(interval.maximum + intercept)}. Il costo di due veicoli rimane ${currency(model.double.total)}. ${interval.containsThreshold ? `Il pareggio è a ${currency(model.threshold, 6)} di noleggio grande.` : "Non vi è un incrocio nell'intervallo mostrato."}`;
    target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" style="aspect-ratio:${width}/${height}" role="img" aria-labelledby="chart-title chart-desc"><title id="chart-title">Confronto dei costi al variare del noleggio del veicolo grande</title><desc id="chart-desc">${escape(chartDesc)}</desc>${grid}<text class="axis-label" x="${margin.left - 10}" y="21" text-anchor="end">€</text><text class="axis-label" x="${margin.left + plotWidth / 2}" y="${height - 8}" text-anchor="middle">Noleggio grande (€/giorno)</text><line x1="${selectedX}" y1="${margin.top}" x2="${selectedX}" y2="${bottom}" stroke="#89997c" stroke-width="1" stroke-dasharray="2 5"/><path class="chart-line" d="M${x(interval.minimum)},${y(interval.minimum + intercept)} L${x(interval.maximum)},${y(interval.maximum + intercept)}" stroke="${colors.green}"/><path class="chart-line" d="M${x(interval.minimum)},${y(model.double.total)} L${x(interval.maximum)},${y(model.double.total)}" stroke="${colors.copper}" stroke-dasharray="9 5"/>${threshold}<circle cx="${selectedX}" cy="${y(model.single.total)}" r="5" fill="${colors.green}" stroke="#eaf0e5" stroke-width="2"><title>Un veicolo con noleggio ${escape(currency(parameters.largeFixed))}: ${escape(currency(model.single.total))}</title></circle><circle cx="${selectedX}" cy="${y(model.double.total)}" r="5" fill="${colors.copper}" stroke="#eaf0e5" stroke-width="2"><title>Due veicoli: ${escape(currency(model.double.total))}</title></circle></svg>`;
  }

  function populateStatic(data) {
    const { instance, results } = data;
    const single = results.scenarios.single_vehicle;
    const double = results.scenarios.two_vehicles;
    const depot = instance.nodes.find((node) => node.id === instance.depot_id);
    const clientCount = instance.nodes.length - 1;
    const totalLoad = instance.nodes.reduce((sum, node) => sum + node.demand_kg, 0);
    text("client-count", integer(clientCount));
    text("node-count", integer(instance.nodes.length));
    text("scenario-count", integer(Object.keys(results.scenarios).length));
    text("hero-description", `${integer(clientCount)} clienti, un deposito a ${depot.name} e due alternative di trasporto: percorsi ottimi e costi diventano una scelta verificabile.`);
    text("location-label", `${depot.name} e comuni vicini · Messina`);
    text("total-load", integer(totalLoad));
    text("demand-total", `${integer(totalLoad)} kg`);
    text("single-capacity", `Capacità ${integer(instance.vehicles.large.capacity_kg)} kg · un autista`);
    text("double-capacity", `Capacità ${integer(instance.vehicles.small.capacity_kg)} kg ciascuno · due autisti`);
    [ ["single", single], ["double", double] ].forEach(([prefix, scenario]) => {
      metric(`${prefix}-distance`, number(scenario.totals.distance_km), "km");
      text(`${prefix}-completion`, roundedDuration(scenario.totals.completion_seconds));
      $( `${prefix}-completion` ).title = `${number(scenario.totals.completion_minutes, 3)} minuti, prima dell’arrotondamento visivo`;
      metric(`${prefix}-hours`, number(scenario.totals.driver_hours, 4), "h");
      text(`${prefix}-enumeration`, `${integer(scenario.enumeration.candidates_generated)} candidati esaminati · ${integer(scenario.enumeration.feasible_candidates)} ammissibili`);
      $(`${prefix}-graph`).innerHTML = graphMarkup(scenario, instance.nodes, prefix);
      $(`${prefix}-routes`).innerHTML = routeDetails(scenario, instance.nodes);
    });
    $("demand-body").innerHTML = instance.nodes.slice(1).map((node) => `<tr><th scope="row"><span class="node-badge">${node.id}</span></th><td>${escape(node.name)}</td><td>${integer(node.demand_kg)} kg</td></tr>`).join("");
    $("matrix-head").innerHTML = `<tr><th scope="col">Da / a</th>${instance.nodes.map((node) => `<th scope="col">${node.id} · ${escape(node.name)}</th>`).join("")}</tr>`;
    $("matrix-body").innerHTML = instance.nodes.map((node, i) => `<tr><th scope="row">${node.id} · ${escape(node.name)}</th>${instance.distances_m[i].map((distance, j) => `<td${i === j ? ' class="diagonal"' : ""}>${i === j ? "0" : number(distance / 1000, 3)}</td>`).join("")}</tr>`).join("");
    text("method-single", `Con un veicolo sono esaminati tutti i ${clientCount}! = ${single.enumeration.candidates_generated} ordini di visita; ${single.enumeration.feasible_candidates} rispettano i vincoli di carico.`);
    text("method-double", `Con due veicoli, ognuno dei ${double.enumeration.permutations} ordini viene diviso nei ${double.enumeration.cuts_per_permutation} punti possibili: ${double.enumeration.candidates_generated} coppie di giri non vuoti, di cui ${double.enumeration.feasible_candidates} ammissibili e ${double.enumeration.discarded_for_capacity} escluse per capacità. I duplicati dovuti allo scambio dei due veicoli sono mantenuti nella ricerca; le coppie ammissibili distinte dopo questo scambio sono ${double.enumeration.feasible_unique_vehicle_exchange}.`);
    text("operations-note", `Per ogni cliente si assumono ${integer(instance.operations.service_minutes_client)} minuti di servizio e per ciascun veicolo ${integer(instance.operations.preparation_minutes_vehicle)} minuti di preparazione. Gli autisti sono remunerati per il tempo operativo frazionabile: non si applicano minimi di turno.`);
  }

  function start(data) {
    const { instance, results } = data;
    if (!instance || !results || !results.scenarios || instance.nodes.length !== 6) throw new Error("I dati del progetto non sono completi.");
    populateStatic(data);
    const baseline = baselineParameters(instance);
    const ids = { largeFixed: "large-fixed", smallFixed: "small-fixed", largeKm: "large-km", smallKm: "small-km", wage: "driver-hour" };
    let currentParameters = { ...baseline };
    let currentModel = economicModel(results, baseline);
    let currentInterval = chartInterval(instance.sensitivity.min_eur, instance.sensitivity.max_eur, currentModel.threshold, baseline.largeFixed);
    const baselineCheck = Math.max(
      Math.abs(currentModel.single.total - results.scenarios.single_vehicle.costs.total_eur),
      Math.abs(currentModel.double.total - results.scenarios.two_vehicles.costs.total_eur),
    );
    if (baselineCheck > 0.000002) throw new Error("I risultati economici non corrispondono ai parametri dell’istanza; rigenerare results.json.");

    function updateDisplay(parameters) {
      const model = economicModel(results, parameters);
      const interval = chartInterval(instance.sensitivity.min_eur, instance.sensitivity.max_eur, model.threshold, parameters.largeFixed);
      currentParameters = { ...parameters };
      currentModel = model;
      currentInterval = interval;
      const slider = $("large-fixed");
      slider.min = String(interval.minimum);
      slider.max = String(interval.maximum);
      slider.value = String(parameters.largeFixed);
      text("large-fixed-value", currency(parameters.largeFixed));
      text("range-min", currency(interval.minimum, 0));
      text("range-max", currency(interval.maximum, 0));
      text("single-cost", currency(model.single.total));
      text("double-cost", currency(model.double.total));
      const equalAtCent = Math.round(model.single.total * 100) === Math.round(model.double.total * 100);
      if (equalAtCent) {
        text("decision-title", "Costi equivalenti al centesimo");
        text("decision-detail", `Entrambi gli scenari valgono ${currency(model.single.total)}; lo scarto non arrotondato è ${currency(Math.abs(model.difference), 6)} per missione.`);
      } else {
        const oneCheaper = model.difference > 0;
        text("decision-title", oneCheaper ? "Conviene un veicolo" : "Convengono due veicoli");
        text("decision-detail", `${currency(model.single.total)} con un mezzo e ${currency(model.double.total)} con due: il risparmio è ${currency(Math.abs(model.difference))} per missione.`);
      }
      text("threshold-value", currency(model.threshold));
      text("threshold-detail", model.threshold < 0
        ? `La soglia teorica è negativa (${currency(model.threshold, 6)}): con questi parametri due veicoli costano meno per qualsiasi noleggio grande non negativo.`
        : `Soglia calcolata: ${currency(model.threshold, 6)}. Sotto questo prezzo conviene un mezzo, sopra convengono due; alla soglia i costi coincidono.`);
      $("cost-components").innerHTML = [
        ["Noleggio", model.single.fixed, model.double.fixed, `${results.scenarios.single_vehicle.totals.vehicle_count} × ${currency(parameters.largeFixed)}`, `${results.scenarios.two_vehicles.totals.vehicle_count} × ${currency(parameters.smallFixed)}`],
        ["Costo chilometrico", model.single.distance, model.double.distance, `${number(model.distanceOne, 4)} km × ${currency(parameters.largeKm)}/km`, `${number(model.distanceTwo, 4)} km × ${currency(parameters.smallKm)}/km`],
        ["Lavoro degli autisti", model.single.driver, model.double.driver, `${number(model.hoursOne, 6)} h × ${currency(parameters.wage)}/h`, `${number(model.hoursTwo, 6)} h × ${currency(parameters.wage)}/h`],
        ["Totale", model.single.total, model.double.total, "", ""],
      ].map((row, index) => `<tr${index === 3 ? ' class="total-row"' : ""}><th scope="row">${row[0]}</th><td>${escape(currency(row[1]))}${row[3] ? `<span class="cost-calc">${escape(row[3])}</span>` : ""}</td><td>${escape(currency(row[2]))}${row[4] ? `<span class="cost-calc">${escape(row[4])}</span>` : ""}</td></tr>`).join("");
      drawCostChart(model, parameters, interval);
    }

    function readInputs() {
      const parameters = {};
      let invalid = false;
      Object.entries(ids).forEach(([key, id]) => {
        const input = $(id);
        const value = input.valueAsNumber;
        const valid = Number.isFinite(value) && value >= Number(input.min || 0) && value <= Number(input.max || Infinity);
        input.setAttribute("aria-invalid", String(!valid));
        if (!valid) invalid = true;
        parameters[key] = value;
      });
      $("input-error").hidden = !invalid;
      if (!invalid) updateDisplay(parameters);
    }

    function reset() {
      $("large-fixed").min = String(instance.sensitivity.min_eur);
      $("large-fixed").max = String(instance.sensitivity.max_eur);
      Object.entries(ids).forEach(([key, id]) => {
        $(id).value = String(baseline[key]);
        $(id).setAttribute("aria-invalid", "false");
      });
      $("input-error").hidden = true;
      updateDisplay({ ...baseline });
    }
    $("cost-form").addEventListener("submit", (event) => event.preventDefault());
    Object.values(ids).forEach((id) => $(id).addEventListener("input", readInputs));
    $("reset-costs").addEventListener("click", reset);
    reset();
    if (typeof ResizeObserver !== "undefined") {
      let previousWidth = 0;
      const observer = new ResizeObserver((entries) => {
        const width = Math.round(entries[0].contentRect.width);
        if (width !== previousWidth) {
          previousWidth = width;
          drawCostChart(currentModel, currentParameters, currentInterval);
        }
      });
      observer.observe($("cost-chart"));
    } else {
      window.addEventListener("resize", () => drawCostChart(currentModel, currentParameters, currentInterval));
    }
  }

  try {
    if (!root.PW_DATA) throw new Error("File data.js non disponibile. Eseguire python3 planner.py e python3 generate_web.py dalla cartella principale del progetto, quindi riaprire questa pagina.");
    start(root.PW_DATA);
  } catch (error) {
    $("data-error").hidden = false;
    $("data-error").textContent = `Impossibile caricare il progetto: ${error.message}`;
    console.error(error);
  }
})(typeof window !== "undefined" ? window : globalThis);
