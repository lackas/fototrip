/* fototrip — map, thumbnail markers, clustering and lightbox.
 *
 * Leaflet and Leaflet.markercluster are loaded as classic scripts and provide
 * the global L. PhotoSwipe is an ES module.
 */
import PhotoSwipeLightbox from "./vendor/photoswipe/photoswipe-lightbox.esm.js";
import PhotoSwipe from "./vendor/photoswipe/photoswipe.esm.js";

const state = {
  photos: [],
  visible: [],
  days: [],
  selectedDay: null,
  bounds: null,
};

const map = L.map("map", { zoomControl: true, worldCopyJump: false });

L.tileLayer(window.FOTOTRIP_TILES.url, {
  attribution: window.FOTOTRIP_TILES.attribution,
  maxZoom: 19,
  subdomains: "abc",
}).addTo(map);

/* A single cluster group, rebuilt whenever the visible set changes. */
const clusterGroup = L.markerClusterGroup({
  maxClusterRadius: 55,
  showCoverageOnHover: false,
  spiderfyOnMaxZoom: true,
  zoomToBoundsOnClick: true,
  iconCreateFunction: (cluster) => {
    const children = cluster.getAllChildMarkers();
    // Show the newest photo in the cluster, so the icon changes as you zoom.
    // Compare real instants, not the ISO strings themselves: this trip's
    // timestamps carry different UTC offsets, so a lexicographic string
    // compare does not agree with time order.
    const newest = children.reduce((a, b) =>
      Date.parse(a.options.photo.t) >= Date.parse(b.options.photo.t) ? a : b
    );
    const count = cluster.getChildCount();
    // Built as a real element rather than an HTML template string: the
    // thumbnail path becomes a CSS value assignment, never markup, so a
    // filename with a quote or '#' can't break out of an attribute.
    const div = document.createElement("div");
    div.className = "cluster-marker";
    div.style.backgroundImage = `url('${newest.options.photo.thumb}')`;
    const badge = document.createElement("span");
    badge.className = "count";
    badge.textContent = String(count);
    div.appendChild(badge);
    return L.divIcon({ className: "", iconSize: [54, 54], html: div });
  },
}).addTo(map);

function markerFor(photo, index) {
  const div = document.createElement("div");
  div.className = "photo-marker";
  div.style.backgroundImage = `url('${photo.thumb}')`;
  const marker = L.marker([photo.lat, photo.lon], {
    photo,
    title: new Date(photo.t).toLocaleString(),
    icon: L.divIcon({
      className: "",
      iconSize: [44, 44],
      iconAnchor: [22, 22],
      html: div,
    }),
  });
  marker.on("click", () => openLightboxAt(index));
  return marker;
}

/* Bounds that never collapse: a single photo, or a burst at one spot, would
 * otherwise give fitBounds a zero-area box and slam the map to max zoom. */
function paddedBounds(photos) {
  if (photos.length === 0) return null;
  const lats = photos.map((p) => p.lat);
  const lons = photos.map((p) => p.lon);
  const pad = 0.004; // ~450 m
  const spanLat = Math.max(...lats) - Math.min(...lats);
  const spanLon = Math.max(...lons) - Math.min(...lons);
  const padLat = spanLat < pad ? pad : 0;
  const padLon = spanLon < pad ? pad : 0;
  return L.latLngBounds(
    [Math.min(...lats) - padLat, Math.min(...lons) - padLon],
    [Math.max(...lats) + padLat, Math.max(...lons) + padLon]
  );
}

function fitTo(photos) {
  const bounds = paddedBounds(photos);
  if (bounds) map.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 });
  else map.setView([0, 0], 2);
}

function setVisible(photos) {
  state.visible = photos;
  clusterGroup.clearLayers();
  clusterGroup.addLayers(photos.map(markerFor));
  fitTo(photos);
  const status = document.getElementById("status");
  if (status) {
    const label = state.selectedDay ? state.selectedDay : "whole trip";
    status.textContent = `${photos.length} photo${photos.length === 1 ? "" : "s"} · ${label}`;
  }
}

/* PhotoSwipe over the currently visible set, so next/prev walks the trip. */
const lightbox = new PhotoSwipeLightbox({
  pswpModule: PhotoSwipe,
  dataSource: [],
  showHideAnimationType: "fade",
  padding: { top: 10, bottom: 10, left: 10, right: 10 },
});
lightbox.init();

function openLightboxAt(index) {
  lightbox.options.dataSource = state.visible.map((photo) => ({
    src: photo.web,
    width: photo.w,
    height: photo.h,
    alt: new Date(photo.t).toLocaleString(),
  }));
  lightbox.loadAndOpen(Math.max(0, Math.min(index, state.visible.length - 1)));
}

async function boot() {
  try {
    const response = await fetch("photos.json");
    if (!response.ok) {
      throw new Error(`photos.json: HTTP ${response.status}`);
    }
    const manifest = await response.json();
    state.photos = manifest.photos;
    state.days = manifest.days;
    state.bounds = manifest.bounds;
    renderTimeline();
    selectDay(null);
    window.dispatchEvent(new CustomEvent("fototrip:loaded"));
  } catch (error) {
    const status = document.getElementById("status");
    if (status) {
      status.textContent = `Could not load photos.json: ${error.message}`;
    }
  }
}

/* ---- day strip ------------------------------------------------------- */

// px. #timeline is 92px tall with 8px top/bottom padding, so its content box
// is 76px (measured: clientHeight 92, padding 8+8). A .day-cell stacks the
// bar, a 4px gap, and a two-line label (measured: 28px at font-size 10px /
// line-height 1.4). 76 - 4 - 28 = 44 is the largest bar that still fits
// without #timeline's overflow-y: hidden clipping it.
const TIMELINE_MAX_BAR = 44;

function selectDay(day) {
  state.selectedDay = day;
  setVisible(day === null ? state.photos : state.photos.filter((p) => p.day === day));
  for (const cell of document.querySelectorAll("#timeline .day-cell")) {
    const cellDay = cell.dataset.day || null;
    cell.setAttribute("aria-pressed", String(cellDay === day));
  }
}

function renderTimeline() {
  const timeline = document.getElementById("timeline");
  if (!timeline) return;
  timeline.textContent = "";

  const busiest = Math.max(1, ...state.days.map((d) => d.count));

  const all = document.createElement("button");
  all.type = "button";
  all.className = "day-cell all";
  all.setAttribute("aria-pressed", "true");
  all.innerHTML =
    `<div class="bar" style="height:${TIMELINE_MAX_BAR}px"></div>` +
    `<span>All<br>${state.photos.length}</span>`;
  all.addEventListener("click", () => selectDay(null));
  timeline.appendChild(all);

  for (const entry of state.days) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "day-cell";
    cell.dataset.day = entry.day;
    cell.setAttribute("aria-pressed", "false");
    const height = Math.max(3, Math.round((entry.count / busiest) * TIMELINE_MAX_BAR));
    const [, month, dayOfMonth] = entry.day.split("-");
    cell.title = `${entry.day} — ${entry.count} photo${entry.count === 1 ? "" : "s"}`;
    cell.innerHTML =
      `<div class="bar" style="height:${height}px"></div>` +
      `<span>${dayOfMonth}.${month}.<br>${entry.count}</span>`;
    cell.addEventListener("click", () => selectDay(entry.day));
    timeline.appendChild(cell);
  }
}

/* Left/right step between days. "All" sits before the first day. */
function stepDay(delta) {
  const order = [null, ...state.days.map((d) => d.day)];
  const current = order.indexOf(state.selectedDay);
  const next = current + delta;
  if (next >= 0 && next < order.length) selectDay(order[next]);
}

document.addEventListener("keydown", (event) => {
  // PhotoSwipe owns the arrows while it is open.
  if (document.querySelector(".pswp")) return;
  if (event.key === "ArrowRight") stepDay(1);
  else if (event.key === "ArrowLeft") stepDay(-1);
});

window.fototrip = {
  state, map, clusterGroup, lightbox,
  setVisible, openLightboxAt, fitTo, selectDay, stepDay, renderTimeline,
};

boot();
