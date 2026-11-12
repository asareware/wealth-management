// Tiny dependency-free SVG charts with hover tooltips.
const Charts = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const el = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  };
  const money = (v, short) => {
    if (short) {
      const a = Math.abs(v);
      if (a >= 1e6) return (v < 0 ? "-" : "") + "$" + (a / 1e6).toFixed(1) + "M";
      if (a >= 1e3) return (v < 0 ? "-" : "") + "$" + (a / 1e3).toFixed(a >= 1e4 ? 0 : 1) + "K";
      return (v < 0 ? "-" : "") + "$" + a.toFixed(0);
    }
    return v.toLocaleString("en-US", { style: "currency", currency: "USD" });
  };
  function niceTicks(min, max, n = 4) {
    if (min === max) { max = min + 1; }
    const step0 = (max - min) / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= step0);
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    const out = []; for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(6));
    return out;
  }
  function frame(container, height) {
    container.innerHTML = "";
    const W = Math.max(container.clientWidth, 280), H = height;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img" }, container);
    const tip = document.createElement("div"); tip.className = "tip"; container.appendChild(tip);
    return { svg, tip, W, H };
  }
  function showTip(tip, container, x, y, html) {
    tip.innerHTML = html; tip.style.display = "block";
    const cw = container.clientWidth, tw = tip.offsetWidth;
    tip.style.left = Math.min(Math.max(x - tw / 2, 0), cw - tw) + "px";
    tip.style.top = (y - tip.offsetHeight - 10) + "px";
  }
  function yAxis(svg, ticks, y, left, right) {
    ticks.forEach(t => {
      el("line", { x1: left, x2: right, y1: y(t), y2: y(t), stroke: t === 0 ? css("--axis") : css("--grid"), "stroke-width": 1 }, svg);
      el("text", { x: left - 8, y: y(t) + 4, "text-anchor": "end" }, svg).textContent = money(t, true);
    });
  }

  // Line (+ soft area) with crosshair tooltip. data: [{date, value}]
  function line(container, data, opts = {}) {
    const H = opts.height || 240, pad = { l: 56, r: 12, t: 12, b: 26 };
    const { svg, tip, W } = frame(container, H);
    if (!data.length) { el("text", { x: W / 2, y: H / 2, "text-anchor": "middle" }, svg).textContent = "No history yet"; return; }
    const vals = data.map(d => d.value);
    const ticks = niceTicks(Math.min(...vals), Math.max(...vals));
    const x = i => pad.l + (data.length === 1 ? 0 : i * (W - pad.l - pad.r) / (data.length - 1));
    const y = v => pad.t + (ticks.at(-1) - v) / (ticks.at(-1) - ticks[0]) * (H - pad.t - pad.b);
    yAxis(svg, ticks, y, pad.l, W - pad.r);
    const color = css("--s1");
    const pts = data.map((d, i) => `${x(i)},${y(d.value)}`);
    el("path", { d: `M${pts[0]} L${pts.join(" L")} L${x(data.length - 1)},${y(ticks[0])} L${x(0)},${y(ticks[0])} Z`,
      fill: color, opacity: 0.08 }, svg);
    el("path", { d: `M${pts.join(" L")}`, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round" }, svg);
    // x labels: ~5 evenly spaced
    const n = Math.min(5, data.length);
    for (let k = 0; k < n; k++) {
      const i = Math.round(k * (data.length - 1) / Math.max(n - 1, 1));
      el("text", { x: x(i), y: H - 6, "text-anchor": k === 0 ? "start" : k === n - 1 ? "end" : "middle" }, svg)
        .textContent = fmtDate(data[i].date, true);
    }
    const cross = el("line", { y1: pad.t, y2: H - pad.b, stroke: css("--axis"), "stroke-width": 1, visibility: "hidden" }, svg);
    const dot = el("circle", { r: 5, fill: color, stroke: css("--card"), "stroke-width": 2, visibility: "hidden" }, svg);
    const hit = el("rect", { x: pad.l, y: 0, width: W - pad.l - pad.r, height: H, fill: "transparent" }, svg);
    hit.addEventListener("mousemove", e => {
      const r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * W / r.width;
      const i = Math.max(0, Math.min(data.length - 1, Math.round((px - pad.l) / ((W - pad.l - pad.r) / Math.max(data.length - 1, 1)))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(data[i].value)); dot.setAttribute("visibility", "visible");
      showTip(tip, container, x(i) * r.width / W, y(data[i].value) * r.height / H,
        `<b>${money(data[i].value)}</b>${fmtDate(data[i].date)}`);
    });
    hit.addEventListener("mouseleave", () => { tip.style.display = "none"; cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); });
  }

  // Vertical bars, one or more series side by side. cats: [label], series: [{name, color, values}]
  function bars(container, cats, series, opts = {}) {
    const H = opts.height || 240, pad = { l: 56, r: 8, t: 12, b: 26 };
    const { svg, tip, W } = frame(container, H);
    const all = series.flatMap(s => s.values);
    const ticks = niceTicks(Math.min(0, ...all), Math.max(0, ...all, 1));
    const y = v => pad.t + (ticks.at(-1) - v) / (ticks.at(-1) - ticks[0]) * (H - pad.t - pad.b);
    yAxis(svg, ticks, y, pad.l, W - pad.r);
    const band = (W - pad.l - pad.r) / cats.length, gap = 2;
    const bw = Math.min(28, (band * 0.7 - gap * (series.length - 1)) / series.length);
    const every = Math.ceil(cats.length / (opts.maxLabels || 12));
    cats.forEach((c, i) => {
      const groupW = bw * series.length + gap * (series.length - 1);
      const x0 = pad.l + i * band + (band - groupW) / 2;
      series.forEach((s, k) => {
        const v = s.values[i] || 0, top = y(Math.max(v, 0)), h = Math.max(Math.abs(y(v) - y(0)), v ? 1 : 0);
        const r = Math.min(4, bw / 2, h);
        const bx = x0 + k * (bw + gap);
        // rounded data-end, square at baseline
        el("path", { d: `M${bx},${top + h} V${top + r} Q${bx},${top} ${bx + r},${top} H${bx + bw - r} Q${bx + bw},${top} ${bx + bw},${top + r} V${top + h} Z`,
          style: `fill:${s.color}` }, svg);
      });
      if (i % every === 0) el("text", { x: pad.l + i * band + band / 2, y: H - 6, "text-anchor": "middle" }, svg).textContent = opts.label ? opts.label(c) : c;
      const hit = el("rect", { x: pad.l + i * band, y: pad.t, width: band, height: H - pad.t - pad.b, fill: "transparent" }, svg);
      hit.addEventListener("mousemove", e => {
        const r = svg.getBoundingClientRect();
        showTip(tip, container, (pad.l + i * band + band / 2) * r.width / W, pad.t + 20,
          `<b>${opts.title ? opts.title(c) : c}</b>` + series.map(s => `${series.length > 1 ? s.name + ": " : ""}${money(s.values[i] || 0)}`).join("<br>"));
        hit.setAttribute("fill", css("--wash"));
      });
      hit.addEventListener("mouseleave", () => { tip.style.display = "none"; hit.setAttribute("fill", "transparent"); });
    });
  }

  function fmtDate(iso, short) {
    const d = new Date(iso + (iso.length === 7 ? "-01" : "") + "T12:00:00");
    if (iso.length === 7) return d.toLocaleDateString("en-US", { month: short ? "short" : "long", year: short ? undefined : "numeric" });
    return d.toLocaleDateString("en-US", short ? { month: "short", day: "numeric" } : { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  }
  return { line, bars, money, fmtDate };
})();
