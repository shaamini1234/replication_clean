/* app.js — the whole front end.
 *
 * It does two things and nothing else:
 *   1. writes pre-formatted strings from data/site.json into [data-f] / [data-t]
 *   2. hands pre-built Chart.js specifications to Chart.js
 *
 * There is no arithmetic here by design: every number, percentage, label, axis
 * tick and tooltip line is computed by python/build_site_data.py against the
 * DuckDB and arrives ready to render. See vercel_site/README.md.
 */
(function () {
  "use strict";

  var DATA_URL = "data/site.json";

  function fail(message, detail) {
    var el = document.getElementById("err");
    if (!el) return;
    el.hidden = false;
    el.textContent = message + (detail ? " — " + detail : "");
    // eslint-disable-next-line no-console
    console.error("[site]", message, detail || "");
  }

  /** Install lookup-only callbacks: axis ticks and tooltips read strings the
   *  back end already formatted. */
  function withLookups(spec) {
    var options = spec.options || {};
    var maps = spec.tickLabels || {};
    Object.keys(maps).forEach(function (axisId) {
      var scale = options.scales && options.scales[axisId];
      if (!scale) return;
      var labels = maps[axisId];
      scale.ticks = Object.assign({}, scale.ticks, {
        callback: function (value) {
          var key = String(value);
          return Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : value;
        }
      });
    });
    options.plugins = Object.assign({}, options.plugins, {
      tooltip: {
        callbacks: {
          title: function (items) {
            if (spec.tooltipTitles) return spec.tooltipTitles[items[0].dataIndex];
            return items[0].label;
          },
          label: function (item) {
            var tips = item.dataset.tips;
            return tips ? tips[item.dataIndex] : item.formattedValue;
          }
        }
      }
    });
    return { type: spec.type, data: spec.data, options: options };
  }

  /* Recession shading. The spans arrive from the back end already expressed in
     the chart's own x coordinates; this only converts them to pixels. */
  var recessionBands = {
    id: "recessionBands",
    beforeDatasetsDraw: function (chart) {
      var bands = chart.$bands;
      if (!bands || !bands.length) return;
      var x = chart.scales.x;
      var area = chart.chartArea;
      var ctx = chart.ctx;
      ctx.save();
      ctx.fillStyle = "rgba(92,98,112,.11)";
      bands.forEach(function (band) {
        var a = x.getPixelForValue(band.x0);
        var b = x.getPixelForValue(band.x1);
        ctx.fillRect(a, area.top, Math.max(1, b - a), area.bottom - area.top);
      });
      ctx.restore();
    }
  };

  function mount(canvas, spec) {
    var chart = new Chart(canvas, withLookups(spec));
    chart.$bands = spec.bands || null;
    if (chart.$bands) chart.update("none");
    return chart;
  }

  /** A chart with more than one view (the geography panel): the toggle buttons
   *  and their labels come from the data, not from the markup. */
  function mountVariants(canvas, spec) {
    var nav = document.querySelector('[data-toggle="' + canvas.id + '"]');
    var chart = null;
    function show(variant, button) {
      if (chart) chart.destroy();
      chart = mount(canvas, variant.spec);
      if (nav) {
        Array.prototype.forEach.call(nav.querySelectorAll("button"), function (b) {
          b.classList.remove("on");
          b.setAttribute("aria-pressed", "false");
        });
      }
      if (button) {
        button.classList.add("on");
        button.setAttribute("aria-pressed", "true");
      }
    }
    if (!nav) {
      show(spec.variants[0], null);
      return;
    }
    spec.variants.forEach(function (variant) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = variant.label;
      button.setAttribute("aria-pressed", "false");
      button.addEventListener("click", function () {
        show(variant, button);
      });
      nav.appendChild(button);
    });
    show(spec.variants[0], nav.querySelector("button"));
  }

  /* The density surface: uniform grid cells rather than boundaries, so colour
     cannot be an artefact of how big an administrative area happens to be. The
     back end supplies each cell's position, size, fill and label. */
  function mountHeat(container, spec) {
    var box = container.querySelector("[data-map-figure]");
    var legendBox = container.querySelector("[data-map-legend]");
    var svgNS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", spec.viewBox);
    svg.setAttribute("role", "img");
    svg.setAttribute("class", "choropleth density");
    svg.setAttribute("aria-label", spec.legendTitle);
    spec.cells.forEach(function (cell) {
      var rect = document.createElementNS(svgNS, "rect");
      rect.setAttribute("x", cell.x);
      rect.setAttribute("y", cell.y);
      rect.setAttribute("width", spec.cellSize);
      rect.setAttribute("height", spec.cellSize);
      rect.setAttribute("fill", cell.fill);
      var title = document.createElementNS(svgNS, "title");
      title.textContent = cell.title;
      rect.appendChild(title);
      svg.appendChild(rect);
    });
    box.textContent = "";
    box.appendChild(svg);
    drawLegend(legendBox, spec.legendTitle, spec.legend, null, null);
  }

  function drawLegend(legendBox, title, bins, noDataColor, noDataLabel) {
    legendBox.textContent = "";
    var caption = document.createElement("span");
    caption.className = "legend-title";
    caption.textContent = title;
    legendBox.appendChild(caption);
    var all = noDataColor ? bins.concat([{ color: noDataColor, label: noDataLabel }]) : bins;
    all.forEach(function (bin) {
      var item = document.createElement("span");
      item.className = "legend-bin";
      var swatch = document.createElement("i");
      swatch.style.background = bin.color;
      item.appendChild(swatch);
      item.appendChild(document.createTextNode(bin.label));
      legendBox.appendChild(item);
    });
  }

  /* Choropleths. The back end supplies projected SVG path strings, one fill and
     one label per area per variant, and the legend. Nothing is computed here. */
  function mountMap(container, spec) {
    var box = container.querySelector("[data-map-figure]");
    var legendBox = container.querySelector("[data-map-legend]");
    var nav = container.querySelector("[data-map-toggle]");
    var svgNS = "http://www.w3.org/2000/svg";

    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", spec.viewBox);
    svg.setAttribute("role", "img");
    svg.setAttribute("class", "choropleth");
    var paths = spec.shapes.map(function (d) {
      var path = document.createElementNS(svgNS, "path");
      path.setAttribute("d", d);
      var title = document.createElementNS(svgNS, "title");
      path.appendChild(title);
      svg.appendChild(path);
      return { path: path, title: title };
    });
    box.textContent = "";
    box.appendChild(svg);

    function show(variant, button) {
      svg.setAttribute("aria-label", variant.legendTitle);
      paths.forEach(function (p, k) {
        p.path.setAttribute("fill", variant.fills[k]);
        p.title.textContent = variant.titles[k];
      });
      drawLegend(legendBox, variant.legendTitle, variant.legend,
                 variant.noDataColor, variant.noDataLabel);
      if (nav) {
        Array.prototype.forEach.call(nav.querySelectorAll("button"), function (b) {
          b.classList.remove("on");
          b.setAttribute("aria-pressed", "false");
        });
      }
      if (button) {
        button.classList.add("on");
        button.setAttribute("aria-pressed", "true");
      }
    }

    if (nav && spec.variants.length > 1) {
      spec.variants.forEach(function (variant) {
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = variant.label;
        button.setAttribute("aria-pressed", "false");
        button.addEventListener("click", function () { show(variant, button); });
        nav.appendChild(button);
      });
      show(spec.variants[0], nav.querySelector("button"));
    } else {
      show(spec.variants[0], null);
    }
  }

  /* Maps are the heaviest payload on the page, so each one is fetched the first
     time it comes near the viewport. */
  function wireMaps() {
    var containers = Array.prototype.slice.call(document.querySelectorAll("[data-map]"));
    if (!containers.length) return;
    var load = function (container) {
      if (container.dataset.loaded) return;
      container.dataset.loaded = "1";
      var file = container.getAttribute("data-map");
      fetch("data/" + file, { cache: "no-cache" })
        .then(function (r) {
          if (!r.ok) throw new Error(file + " returned " + r.status);
          return r.json();
        })
        .then(function (spec) {
          if (spec.cells) mountHeat(container, spec);
          else mountMap(container, spec);
        })
        .catch(function (e) { fail("Could not load a map", String(e)); });
    };
    var MARGIN = 800;
    /* A sweep covers what an observer can miss: a long scroll jump, an anchor
       link or find-in-page can move past a container without any frame ever
       observing it mid-viewport. */
    var sweep = function () {
      containers.forEach(function (c) {
        if (c.dataset.loaded) return;
        var box = c.getBoundingClientRect();
        if (box.top < window.innerHeight + MARGIN && box.bottom > -MARGIN) load(c);
      });
    };
    if ("IntersectionObserver" in window) {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            load(entry.target);
            observer.unobserve(entry.target);
          }
        });
      }, { rootMargin: MARGIN + "px" });
      containers.forEach(function (c) { observer.observe(c); });
    }
    var queued = false;
    var onScroll = function () {
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(function () { queued = false; sweep(); });
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    sweep();

    /* Proximity loading alone leaves a blank frame for any map the reader jumps
       past — an anchor link, find-in-page, or end-of-page key. Once the charts
       are up, fetch whatever is still outstanding regardless of position. */
    var loadRemaining = function () { containers.forEach(load); };
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(loadRemaining, { timeout: 2500 });
    } else {
      window.setTimeout(loadRemaining, 2000);
    }
  }

  function render(payload) {
    var missing = [];

    Array.prototype.forEach.call(document.querySelectorAll("[data-f]"), function (el) {
      var key = el.getAttribute("data-f");
      var value = payload.figures[key];
      if (value === undefined) {
        missing.push(key);
        el.textContent = "—";
        el.classList.add("gap");
      } else {
        el.textContent = value;
      }
    });

    Array.prototype.forEach.call(document.querySelectorAll("[data-t]"), function (el) {
      var key = el.getAttribute("data-t");
      var value = payload.text[key];
      if (value === undefined) {
        missing.push(key);
        el.textContent = "—";
        el.classList.add("gap");
      } else {
        el.innerHTML = value;
      }
    });

    Chart.register(recessionBands);
    Chart.defaults.color = "#5c6270";
    Chart.defaults.font.family = "-apple-system,Segoe UI,Helvetica,Arial,sans-serif";
    Chart.defaults.font.size = 12;

    Object.keys(payload.charts).forEach(function (id) {
      var canvas = document.getElementById(id);
      if (!canvas) return;
      var spec = payload.charts[id];
      try {
        if (spec.variants) mountVariants(canvas, spec);
        else mount(canvas, spec);
      } catch (e) {
        fail("A chart failed to render (" + id + ")", String(e));
      }
    });

    wireMaps();

    if (missing.length) {
      fail("Some figures are missing from the published data", missing.join(", "));
    }
  }

  function start() {
    if (typeof Chart === "undefined") {
      fail("The charting library did not load");
      return;
    }
    fetch(DATA_URL, { cache: "no-cache" })
      .then(function (response) {
        if (!response.ok) throw new Error(DATA_URL + " returned " + response.status);
        return response.json();
      })
      .then(render)
      .catch(function (e) {
        fail("Could not load the figures", String(e));
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
