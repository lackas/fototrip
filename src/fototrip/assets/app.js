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
  tiles: null,
};

const map = L.map("map", { zoomControl: true, worldCopyJump: false });

/* Where the tiles come from travels in photos.json, not in an inline script in
 * the page: an inline script is the one thing that would force
 * `script-src 'unsafe-inline'` on whatever serves this. The layer is therefore
 * added in boot(), once the manifest has arrived. */
const DEFAULT_TILES = {
  url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
};

function addTileLayer(tiles) {
  // A site built before the manifest carried this still gets a map.
  const source = tiles && tiles.url ? tiles : DEFAULT_TILES;
  state.tiles = source;
  L.tileLayer(source.url, {
    attribution: source.attribution || DEFAULT_TILES.attribution,
    maxZoom: 19,
    // The site sends `Referrer-Policy: no-referrer`, but OpenStreetMap blocks
    // browser tile requests without a Referer. The origin alone is enough.
    referrerPolicy: "strict-origin",
  }).addTo(map);
}

/* Photo id -> its marker, rebuilt alongside the cluster group below.
 * Closing the lightbox needs the marker itself, not just the coordinates:
 * whether the photo is hidden inside a cluster is what decides whether the
 * zoom has to change. */
const markers = new Map();

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

/* Photos carry their own UTC offset, and the whole point of this project is
 * that the offset is not where the photo was taken: the phones stayed on
 * their home time while travelling. `new Date(t).toLocaleString()` renders in
 * the VIEWER's timezone, so a photo taken at 20:30 five hours west would read 01:30
 * the next day for someone in Cologne. The parts are therefore read straight
 * out of the ISO string; only the weekday and month names come from Intl, and
 * those are resolved against a UTC date built from those same parts so they
 * cannot drift either.
 */
const CAPTURE_STAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;

function formatCaptureStamp(iso) {
  const match = CAPTURE_STAMP.exec(iso ?? "");
  if (!match) return "";
  const [, year, month, day, hour, minute] = match;
  const names = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  let weekday = names.toLocaleDateString("de-DE", { weekday: "short", timeZone: "UTC" });
  // Chromium's ICU returns "Fr", other builds "Fr."; German wants the dot.
  if (!weekday.endsWith(".")) weekday += ".";
  const monthName = names.toLocaleDateString("de-DE", { month: "long", timeZone: "UTC" });
  return `${weekday}, ${Number(day)}. ${monthName} ${year} \u00b7 ${hour}:${minute}`;
}

function markerFor(photo, index) {
  const div = document.createElement("div");
  div.className = "photo-marker";
  div.style.backgroundImage = `url('${photo.thumb}')`;
  const marker = L.marker([photo.lat, photo.lon], {
    photo,
    title: formatCaptureStamp(photo.t),
    icon: L.divIcon({
      className: "",
      iconSize: [44, 44],
      iconAnchor: [22, 22],
      html: div,
    }),
  });
  marker.on("click", () => openLightboxAt(index));
  markers.set(photo.id, marker);
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
  markers.clear();
  clusterGroup.addLayers(photos.map(markerFor));
  fitTo(photos);
  const status = document.getElementById("status");
  if (status) {
    const label = state.selectedDay ? state.selectedDay : "whole trip";
    status.textContent = `${photos.length} photo${photos.length === 1 ? "" : "s"} · ${label}`;
  }
}

/* The small map in the lightbox: city level, and only on screens wide enough
 * that it does not cover the photo. */
const MINIMAP_ZOOM = 12;
const MINIMAP_MIN_WIDTH = 900;
let minimap = null;

/* PhotoSwipe over the currently visible set, so next/prev walks the trip. */
const lightbox = new PhotoSwipeLightbox({
  pswpModule: PhotoSwipe,
  dataSource: [],
  showHideAnimationType: "fade",
  padding: { top: 10, bottom: 10, left: 10, right: 10 },
});
lightbox.init();

/* PhotoSwipe v5 ships no caption of its own, so register one as a UI element
 * and refill it on every slide change. */
lightbox.on("uiRegister", () => {
  lightbox.pswp.ui.registerElement({
    name: "custom-caption",
    appendTo: "root",
    onInit: (element, pswp) => {
      const fill = () => {
        const photo = state.visible[pswp.currIndex];
        element.replaceChildren();
        if (!photo) return;

        const when = document.createElement("div");
        when.className = "caption-when";
        when.textContent = formatCaptureStamp(photo.t);
        element.appendChild(when);

        if (photo.place) {
          const where = document.createElement("div");
          where.className = "caption-where";
          where.textContent = photo.place;
          element.appendChild(where);
        }
      };
      pswp.on("change", fill);
      fill();
    },
  });

  // Paging through a whole trip loses the sense of place, so a desktop-sized
  // screen gets a small map of where each photo was taken. On a phone it would
  // sit on top of the photo, so there it is not built at all.
  if (!window.matchMedia(`(min-width: ${MINIMAP_MIN_WIDTH}px)`).matches) return;
  lightbox.pswp.ui.registerElement({
    name: "minimap",
    appendTo: "root",
    onInit: (element, pswp) => {
      // Leaflet sets `position: relative` inline on a container whose
      // computed position it cannot read yet, and inline beats app.css. Said
      // here first, it leaves the corner placement alone.
      element.style.position = "absolute";
      minimap = L.map(element, {
        zoomControl: false,
        dragging: false,
        scrollWheelZoom: false,
        doubleClickZoom: false,
        boxZoom: false,
        keyboard: false,
        touchZoom: false,
      });
      minimap.attributionControl.setPrefix(false);
      L.tileLayer(state.tiles.url, {
        attribution: state.tiles.attribution,
        referrerPolicy: "strict-origin",
        maxZoom: 19,
      }).addTo(minimap);
      const dot = L.circleMarker([0, 0], {
        radius: 6,
        weight: 2,
        color: "#fff",
        fillColor: "#e8833a",
        fillOpacity: 1,
      }).addTo(minimap);
      const follow = () => {
        const photo = state.visible[pswp.currIndex];
        if (!photo) return;
        dot.setLatLng([photo.lat, photo.lon]);
        minimap.setView([photo.lat, photo.lon], MINIMAP_ZOOM);
      };
      pswp.on("change", follow);
      follow();
      // Built while the lightbox is still fading in, so measure again once it
      // has its real size, or the tiles are laid out for a zero-sized box.
      pswp.on("openingAnimationEnd", () => minimap.invalidateSize());
      pswp.on("destroy", () => {
        minimap.remove();
        minimap = null;
      });
    },
  });
});

/* Zoom to settle at when a photo has to be dug out of a cluster. Same cap
 * fitTo uses, so the map lands at one familiar scale whenever it decides for
 * you rather than at whatever depth the cluster happened to break up. */
const PHOTO_ZOOM = 16;

/* Closing the lightbox puts you back on the map where that photo was taken --
 * the one you were looking at when you closed, not the one you opened, so
 * paging through with next/prev and then leaving lands you where you ended up.
 *
 * The zoom you were working in is kept wherever it can be. It is only raised
 * when the photo's marker is hidden inside a cluster at the current zoom,
 * because centring on a cluster badge of four hundred tells you nothing about
 * where the photo was -- which is the entire question this is answering.
 */
function revealOnMap(photo) {
  if (!photo) return;
  const target = [photo.lat, photo.lon];
  const marker = markers.get(photo.id);
  const hiddenInCluster = !!marker && clusterGroup.getVisibleParent(marker) !== marker;
  if (hiddenInCluster && map.getZoom() < PHOTO_ZOOM) map.setView(target, PHOTO_ZOOM);
  else map.panTo(target);
}

lightbox.on("close", () => {
  revealOnMap(state.visible[lightbox.pswp.currIndex]);
});

function openLightboxAt(index) {
  lightbox.options.dataSource = state.visible.map((photo) => ({
    src: photo.web,
    width: photo.w,
    height: photo.h,
    alt: formatCaptureStamp(photo.t),
  }));
  lightbox.loadAndOpen(Math.max(0, Math.min(index, state.visible.length - 1)));
}

async function boot() {
  // Narrowly scoped to the fetch and the parse: a bug in renderTimeline() or
  // selectDay() below must surface as a real console error, not get
  // relabelled as a "Could not load photos.json" message it has nothing to
  // do with.
  let manifest;
  try {
    const response = await fetch("photos.json");
    if (!response.ok) {
      throw new Error(`photos.json: HTTP ${response.status}`);
    }
    manifest = await response.json();
  } catch (error) {
    console.error(error);
    const status = document.getElementById("status");
    if (status) {
      status.textContent = `Could not load photos.json: ${error.message}`;
    }
    return;
  }
  addTileLayer(manifest.tiles);
  state.photos = manifest.photos;
  state.days = manifest.days;
  state.bounds = manifest.bounds;
  renderTimeline();
  selectDay(null);
  window.dispatchEvent(new CustomEvent("fototrip:loaded"));
}

/* ---- day strip ------------------------------------------------------- */

// px. #timeline is 92px tall with 8px top/bottom padding, so its content box
// is 76px (measured: clientHeight 92, padding 8+8). A .day-cell stacks the
// bar, a 4px gap, and a two-line label (measured: 28px at font-size 10px /
// line-height 1.4). 76 - 4 - 28 = 44 is the largest bar that still fits
// without #timeline's overflow-y: hidden clipping it.
const TIMELINE_MAX_BAR = 44;

/* A second click on the day already selected opens its first photo: a way
 * into the pictures without zooming until a single marker appears. */
function clickDay(day) {
  if (day === state.selectedDay && state.visible.length > 0) openLightboxAt(0);
  else selectDay(day);
}

function selectDay(day) {
  state.selectedDay = day;
  setVisible(day === null ? state.photos : state.photos.filter((p) => p.day === day));
  for (const cell of document.querySelectorAll("#timeline .day-cell")) {
    const cellDay = cell.dataset.day || null;
    cell.setAttribute("aria-pressed", String(cellDay === day));
  }
}

/* A `.bar` at the given height plus a two-line `<span>` label, the same
 * structure the innerHTML template strings used to build. Built as real
 * nodes rather than interpolated markup for the same reason the marker and
 * cluster icons were: today's values are machine-generated integers and
 * ISO date slices with no injection risk, but it is the same construct, and
 * consistent is easier to keep safe than "safe here, not there". */
function dayCellContents(barHeightPx, labelLine1, count) {
  const bar = document.createElement("div");
  bar.className = "bar";
  bar.style.height = `${barHeightPx}px`;

  const label = document.createElement("span");
  label.appendChild(document.createTextNode(labelLine1));
  label.appendChild(document.createElement("br"));
  label.appendChild(document.createTextNode(String(count)));

  return [bar, label];
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
  for (const node of dayCellContents(TIMELINE_MAX_BAR, "All", state.photos.length)) {
    all.appendChild(node);
  }
  all.addEventListener("click", () => clickDay(null));
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
    for (const node of dayCellContents(height, `${dayOfMonth}.${month}.`, entry.count)) {
      cell.appendChild(node);
    }
    cell.addEventListener("click", () => clickDay(entry.day));
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
  state, map, clusterGroup, lightbox, markers, addTileLayer,
  setVisible, openLightboxAt, fitTo, selectDay, stepDay, renderTimeline, revealOnMap,
  get minimap() {
    return minimap;
  },
};

boot();
