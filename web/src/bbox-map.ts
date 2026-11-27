import landUrl from "./map-land.json?url";
import detailUrl from "./map-detail.json?url";
import { splitBox } from "./ranking";
import type { BBox } from "./types";

type Point = [number, number];
type Ring = Point[];
type Shape = { bounds: BBox; path: Path2D };
type Place = [name: string, country: string, longitude: number, latitude: number, rank: number];
type Footprint = { title: string; parts: BBox[] };
type Frame = { center: Point; span: number };
type Gesture =
  | { kind: "pan"; origin: Point; frame: Frame }
  | { kind: "draw"; origin: Point; anchor: Point }
  | { kind: "pinch"; origin: Point; distance: number; frame: Frame };

const WORLD: Frame = { center: [0, 0], span: 360 };
const MIN_SPAN = 0.025;
const DETAIL_SPAN = 65;
const ZOOM = 1.6;

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const wrap = (longitude: number) => ((longitude + 180) % 360 + 360) % 360 - 180;
const round = (value: number) => Number(value.toFixed(6));
const mid = (a: Point, b: Point): Point => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];

function frameAt(center: Point, requested: number): Frame {
  const span = clamp(requested, MIN_SPAN, 360);
  const halfHeight = span / 4;
  return {
    center: [wrap(center[0]), clamp(center[1], -90 + halfHeight, 90 - halfHeight)],
    span,
  };
}

function frameBounds({ center: [lon, lat], span }: Frame): BBox {
  return [lon - span / 2, lat - span / 4, lon + span / 2, lat + span / 4];
}

function continuousBounds([west, south, east, north]: BBox): BBox {
  return [west, south, east < west ? east + 360 : east, north];
}

export function fitBounds(area: BBox): BBox {
  const [west, south, east, north] = continuousBounds(area);
  const span = Math.max((east - west) * 1.25, (north - south) * 2.5, MIN_SPAN);
  return frameBounds(span >= 360 ? WORLD : frameAt(mid([west, south], [east, north]), span));
}

function position(frame: Frame, fraction: Point): Point {
  return [
    frame.center[0] + (fraction[0] - 0.5) * frame.span,
    frame.center[1] + (0.5 - fraction[1]) * frame.span / 2,
  ];
}

function moveAnchor(frame: Frame, from: Point, to: Point, requested: number): Frame {
  const span = clamp(requested, MIN_SPAN, 360);
  const [longitude, latitude] = position(frame, from);
  return frameAt([longitude + (0.5 - to[0]) * span, latitude + (to[1] - 0.5) * span / 2], span);
}

function selection(a: Point, b: Point): BBox {
  const west = Math.min(a[0], b[0]);
  const east = Math.max(a[0], b[0]);
  const eastWrapped = wrap(east);
  return [
    east - west >= 360 ? -180 : round(wrap(west)),
    round(Math.min(a[1], b[1])),
    east - west >= 360 || (eastWrapped === -180 && west !== east) ? 180 : round(eastWrapped),
    round(Math.max(a[1], b[1])),
  ];
}

function overlaps(a: BBox, b: BBox): boolean {
  return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];
}

function shift([w, s, e, n]: BBox, longitudeShift: number): BBox {
  return [w + longitudeShift, s, e + longitudeShift, n];
}

function makeShapes(rings: Ring[]): Shape[] {
  return rings.map((ring) => {
    const path = new Path2D();
    const bounds: BBox = [Infinity, Infinity, -Infinity, -Infinity];
    for (const [i, [longitude, latitude]] of ring.entries()) {
      if (i === 0) path.moveTo(longitude, latitude);
      else path.lineTo(longitude, latitude);
      bounds[0] = Math.min(bounds[0], longitude);
      bounds[1] = Math.min(bounds[1], latitude);
      bounds[2] = Math.max(bounds[2], longitude);
      bounds[3] = Math.max(bounds[3], latitude);
    }
    path.closePath();
    return { bounds, path };
  });
}

async function loadAsset<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin", redirect: "error" });
  if (!response.ok) throw new Error("Map data is unavailable.");
  return response.json() as Promise<T>;
}

function searchKey(value: string): string {
  return value.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim();
}

function placeLabel([name, country]: Place): string {
  return country ? name + ", " + country : name;
}

export async function setupMap(writeArea: (area: BBox) => void) {
  const canvas = document.querySelector<HTMLCanvasElement>("#area-map")!;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Map preview is unavailable in this browser.");
  const ctx = context;
  const note = document.querySelector("#map-selection")!;
  const button = (id: string) => document.querySelector<HTMLButtonElement>(id)!;
  const fit = button("#map-fit");
  const pan = button("#map-pan");
  const drawArea = button("#map-draw");
  const zoomIn = button("#map-zoom-in");
  const zoomOut = button("#map-zoom-out");
  const city = document.querySelector<HTMLInputElement>("#map-place")!;
  const cities = document.querySelector<HTMLDataListElement>("#map-places")!;
  const cityStatus = document.querySelector("#map-place-status")!;

  const overview = makeShapes(await loadAsset<Ring[]>(landUrl));
  let detail: Shape[] | undefined;
  let places: Place[] = [];
  let detailRequest: Promise<void> | undefined;
  let mode: "pan" | "draw" = "pan";
  let frame = WORLD;
  let area: BBox | undefined;
  let footprint: Footprint | undefined;
  let gesture: Gesture | undefined;
  let draft: BBox | undefined;
  let marker: Place | undefined;
  let pendingFrame: number | undefined;
  const pointers = new Map<number, Point>();
  const width = canvas.width;
  const height = canvas.height;
  const offsets = [-360, 0, 360];

  function requestDetail(): Promise<void> {
    detailRequest ??= loadAsset<{ rings: Ring[]; places: Place[] }>(detailUrl).then((asset) => {
      detail = makeShapes(asset.rings);
      places = asset.places;
      cities.replaceChildren(...places.map((place) => new Option(placeLabel(place), placeLabel(place))));
      redraw();
    });
    return detailRequest;
  }

  function coords(longitude: number, latitude: number): Point {
    return [
      width * (0.5 + (longitude - frame.center[0]) / frame.span),
      height * (0.5 - (latitude - frame.center[1]) * 2 / frame.span),
    ];
  }

  function drawLand(view: BBox, px: number) {
    const shapes = detail && frame.span <= DETAIL_SPAN ? detail : overview;
    const sx = width / frame.span;
    const sy = 2 * height / frame.span;
    ctx.fillStyle = "#f0f3ea";
    ctx.strokeStyle = "#a8ae9e";
    ctx.lineWidth = 0.8 * px / sx;
    for (const offset of offsets) {
      const path = new Path2D();
      for (const shape of shapes) {
        if (overlaps(view, shift(shape.bounds, offset))) path.addPath(shape.path);
      }
      ctx.save();
      ctx.setTransform(sx, 0, 0, -sy, (offset - view[0]) * sx, view[3] * sy);
      ctx.fill(path, "evenodd");
      ctx.stroke(path);
      ctx.restore();
    }
  }

  function drawGrid([w, s, e, n]: BBox, px: number) {
    const ideal = frame.span / 11;
    const magnitude = 10 ** Math.floor(Math.log10(ideal));
    const step = magnitude * ([1, 2, 5, 10].find(m => m * magnitude >= ideal) ?? 10);
    ctx.strokeStyle = "#35455e17";
    ctx.lineWidth = px;
    ctx.beginPath();
    for (let lon = Math.ceil(w / step) * step; lon <= e; lon += step) {
      ctx.moveTo(...coords(lon, s));
      ctx.lineTo(...coords(lon, n));
    }
    for (let lat = Math.ceil(s / step) * step; lat <= n; lat += step) {
      ctx.moveTo(...coords(w, lat));
      ctx.lineTo(...coords(e, lat));
    }
    ctx.stroke();
  }

  function drawBox(box: BBox, view: BBox, outline: string, fill: string, px: number, dashed = false) {
    for (const offset of offsets) {
      const [w, s, e, n] = shift(box, offset);
      if (!overlaps(view, [w, s, e, n])) continue;
      const [left, top] = coords(w, n);
      const [right, bottom] = coords(e, s);
      ctx.fillStyle = fill;
      ctx.fillRect(left, top, right - left, bottom - top);
      ctx.strokeStyle = outline;
      ctx.lineWidth = 2 * px;
      ctx.setLineDash(dashed ? [7 * px, 4 * px] : []);
      ctx.strokeRect(left, top, right - left, bottom - top);
      ctx.setLineDash([]);
    }
  }

  function corners(box: BBox, view: BBox): [corner: Point, opposite: Point][] {
    const pairs: [Point, Point][] = [];
    for (const offset of offsets) {
      const [w, s, e, n] = shift(continuousBounds(box), offset);
      if (overlaps(view, [w, s, e, n])) {
        pairs.push([[w, n], [e, s]], [[e, n], [w, s]], [[e, s], [w, n]], [[w, s], [e, n]]);
      }
    }
    return pairs;
  }

  function drawPlaces(px: number) {
    const shown: BBox[] = [];
    const rank = frame.span <= 9 ? Infinity : frame.span <= 32 ? 6 : 3;
    ctx.font = "600 " + 12 * px + "px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    for (const place of marker ? [marker, ...places] : places) {
      const [name, , longitude, latitude, priority] = place;
      if (place !== marker && (priority > rank || frame.span > DETAIL_SPAN)) continue;
      const localLongitude = frame.center[0] + wrap(longitude - frame.center[0]);
      const [x, y] = coords(localLongitude, latitude);
      const label: BBox = [x - 4 * px, y - 8 * px, x + ctx.measureText(name).width + 11 * px, y + 8 * px];
      if (label[0] < 0 || label[1] < 0 || label[2] > width || label[3] > height ||
          shown.some(previous => overlaps(previous, label))) continue;
      shown.push(label);
      ctx.beginPath();
      ctx.arc(x, y, (place === marker ? 3.4 : 2.1) * px, 0, Math.PI * 2);
      ctx.fillStyle = "#1e364a";
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2.7 * px;
      ctx.strokeText(name, x + 6 * px, y);
      ctx.fillText(name, x + 6 * px, y);
      if (shown.length === 28) break;
    }
  }

  function paint() {
    pendingFrame = undefined;
    const displayWidth = canvas.clientWidth;
    if (!displayWidth) return;
    const px = width / displayWidth;
    const view = frameBounds(frame);
    ctx.fillStyle = "#dfeaf1";
    ctx.fillRect(0, 0, width, height);
    drawLand(view, px);
    drawGrid(view, px);

    const picked = draft ?? area;
    const requested = picked ? splitBox(picked) : [];
    const overlap = footprint && picked ?
      footprint.parts.some(part => requested.some(box => overlaps(part, box))) : undefined;
    for (const part of footprint?.parts ?? []) {
      drawBox(part, view, overlap === false ? "#933e52" : "#28755c", overlap === false ? "#933e523d" : "#28755c35", px);
    }
    for (const part of requested) drawBox(part, view, "#754813", "#eeb64d42", px, true);
    drawPlaces(px);
    if (picked && mode === "draw") {
      for (const [corner] of corners(picked, view)) {
        const [x, y] = coords(...corner);
        const size = 7 * px;
        ctx.fillStyle = "#fffaf1";
        ctx.strokeStyle = "#754813";
        ctx.lineWidth = 1.5 * px;
        ctx.fillRect(x - size / 2, y - size / 2, size, size);
        ctx.strokeRect(x - size / 2, y - size / 2, size, size);
      }
    }

    const state = overlap === true ? "intersects the area" : overlap === false ? "outside the area" : "coverage extent";
    const location = footprint ? footprint.title + " · " + state : "";
    const crosses = picked && picked[0] > picked[2] ? "Area crosses the 180° meridian." : "";
    const message = [location, crosses].filter(Boolean).join(" ");
    if (note.textContent !== message) note.textContent = message;
  }

  function redraw() {
    pendingFrame ??= requestAnimationFrame(paint);
  }

  function setFrame(next: Frame) {
    frame = next;
    zoomIn.disabled = frame.span <= MIN_SPAN;
    zoomOut.disabled = frame.span >= 360;
    if (frame.span <= DETAIL_SPAN) void requestDetail().catch(() => {});
    redraw();
  }

  function zoom(multiplier: number, anchor: Point = [0.5, 0.5]) {
    setFrame(moveAnchor(frame, anchor, anchor, frame.span * multiplier));
  }

  function modeTo(next: typeof mode) {
    mode = next;
    canvas.dataset.mode = next;
    pan.setAttribute("aria-pressed", String(next === "pan"));
    drawArea.setAttribute("aria-pressed", String(next === "draw"));
    redraw();
  }

  function canvasPoint(event: { clientX: number; clientY: number }): Point {
    const rect = canvas.getBoundingClientRect();
    return [
      (event.clientX - rect.left - canvas.clientLeft) / canvas.clientWidth,
      (event.clientY - rect.top - canvas.clientTop) / canvas.clientHeight,
    ];
  }

  function within(point: Point): Point {
    return [clamp(point[0], 0, 1), clamp(point[1], 0, 1)];
  }

  function distance(a: Point, b: Point): number {
    return Math.hypot((a[0] - b[0]) * canvas.clientWidth, (a[1] - b[1]) * canvas.clientHeight);
  }

  function adjustmentAnchor(point: Point): Point {
    const positionAtPoint = position(frame, within(point));
    if (area) {
      for (const [corner, opposite] of corners(area, frameBounds(frame))) {
        const [x, y] = coords(...corner);
        if (distance([x / width, y / height], point) <= 12) return opposite;
      }
    }
    return positionAtPoint;
  }

  canvas.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch" && (event.button !== 0 || pointers.size)) return;
    if (pointers.size >= 2) return;
    const point = canvasPoint(event);
    canvas.focus({ preventScroll: true });
    canvas.setPointerCapture(event.pointerId);
    pointers.set(event.pointerId, point);
    canvas.classList.add("is-dragging");
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      gesture = { kind: "pinch", origin: mid(a, b), distance: Math.max(distance(a, b), 1), frame };
      draft = undefined;
      redraw();
    } else if (mode === "draw") {
      gesture = { kind: "draw", origin: point, anchor: adjustmentAnchor(point) };
    } else {
      gesture = { kind: "pan", origin: point, frame };
    }
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId) || !gesture) return;
    const point = canvasPoint(event);
    pointers.set(event.pointerId, point);
    if (gesture.kind === "pinch") {
      const [a, b] = [...pointers.values()];
      const span = gesture.frame.span * gesture.distance / Math.max(distance(a, b), 1);
      setFrame(moveAnchor(gesture.frame, gesture.origin, mid(a, b), span));
    } else if (gesture.kind === "pan") {
      setFrame(moveAnchor(gesture.frame, gesture.origin, point, gesture.frame.span));
    } else {
      draft = selection(gesture.anchor, position(frame, within(point)));
      redraw();
    }
  });

  function endPointer(event: PointerEvent, finish: boolean) {
    if (!pointers.delete(event.pointerId)) return;
    if (finish && gesture?.kind === "draw") {
      const point = canvasPoint(event);
      if (distance(gesture.origin, point) >= 3) {
        const next = selection(gesture.anchor, position(frame, within(point)));
        if (next[0] !== next[2] && next[1] !== next[3]) {
          area = next;
          fit.disabled = false;
          writeArea(next);
        }
      }
    }
    const remaining = pointers.values().next().value;
    gesture = remaining ? { kind: "pan", origin: remaining, frame } : undefined;
    draft = undefined;
    canvas.classList.toggle("is-dragging", !!remaining);
    redraw();
  }

  canvas.addEventListener("pointerup", event => endPointer(event, true));
  canvas.addEventListener("pointercancel", event => endPointer(event, false));
  canvas.addEventListener("lostpointercapture", event => endPointer(event, false));
  canvas.addEventListener("wheel", (event) => {
    if (document.activeElement !== canvas && !event.ctrlKey) return;
    event.preventDefault();
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1);
    zoom(Math.exp(clamp(delta / 360, -0.55, 0.55)), within(canvasPoint(event)));
  }, { passive: false });

  canvas.addEventListener("keydown", (event) => {
    const offsets: Record<string, Point> = { ArrowLeft: [-0.18, 0], ArrowRight: [0.18, 0], ArrowUp: [0, 0.09], ArrowDown: [0, -0.09] };
    const offset = offsets[event.key];
    if (offset) {
      setFrame(frameAt([frame.center[0] + offset[0] * frame.span, frame.center[1] + offset[1] * frame.span], frame.span));
    } else if (event.key === "+" || event.key === "=") zoom(1 / ZOOM);
    else if (event.key === "-" || event.key === "_") zoom(ZOOM);
    else if (event.key === "Home") setFrame(WORLD);
    else return;
    event.preventDefault();
  });

  async function findCity() {
    const key = searchKey(city.value);
    if (!key) return;
    try {
      await requestDetail();
      const exact = places.filter(place => searchKey(placeLabel(place)) === key || searchKey(place[0]) === key);
      const matches = exact.length ? exact : places.filter(place => searchKey(placeLabel(place)).includes(key));
      if (matches.length !== 1) {
        cityStatus.textContent = matches.length ? "Choose a city and country from the suggestions." : "City not found in the map data.";
        return;
      }
      const [place] = matches;
      marker = place;
      city.value = placeLabel(place);
      cityStatus.textContent = "";
      setFrame(frameAt([place[2], place[3]], 1.5));
      canvas.focus({ preventScroll: true });
    } catch {
      cityStatus.textContent = "City lookup is unavailable.";
    }
  }

  city.addEventListener("focus", () => { void requestDetail().catch(() => {}); });
  city.addEventListener("input", () => { cityStatus.textContent = ""; });
  city.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      void findCity();
    }
  });
  button("#map-place-go").addEventListener("click", () => { void findCity(); });

  pan.addEventListener("click", () => modeTo("pan"));
  drawArea.addEventListener("click", () => modeTo("draw"));
  zoomIn.addEventListener("click", () => zoom(1 / ZOOM));
  zoomOut.addEventListener("click", () => zoom(ZOOM));
  fit.addEventListener("click", () => {
    if (!area) return;
    const [w, s, e, n] = fitBounds(area);
    setFrame({ center: mid([w, s], [e, n]), span: e - w });
  });
  button("#map-world").addEventListener("click", () => setFrame(WORLD));

  const canvasSize = new ResizeObserver(redraw);
  canvasSize.observe(canvas);
  modeTo("pan");
  setFrame(WORLD);
  return {
    setArea(value: BBox | undefined) {
      area = value;
      fit.disabled = !area;
      redraw();
    },
    setCoverage(value: Footprint | undefined) {
      footprint = value;
      redraw();
    },
  };
}
