// Replay viewer: draws the MuJoCo scene's primitive geoms and moves their bodies from the frames web/build.py baked.
// The policy that recorded a replay also runs here (onnxruntime-web) on the recorded observations, so the page shows
// real in-browser inference latency and checks the output against the recorded action. Tab: diagnostics overlay.
// 30 s without input: demo mode (idle.js).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { IdleTimer, DWELL_SECONDS } from "./idle.js";

const $ = (id) => document.getElementById(id);
const fail = (msg) => { const e = $("err"); e.textContent = msg; e.style.display = "grid"; throw new Error(msg); };
const getJSON = async (url) => { const r = await fetch(url); if (!r.ok) fail(`${url}: HTTP ${r.status}`); return r.json(); };

// ---- renderer, camera, lights ----
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
$("view").appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1b1e24);
scene.fog = new THREE.Fog(0x1b1e24, 25, 60);
const camera = new THREE.PerspectiveCamera(45, 1, 0.05, 200);
camera.position.set(4, 2.4, 4);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1, 0);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x3a3020, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 2.2);
sun.position.set(6, 12, 4);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, far: 40 });
scene.add(sun, sun.target);

// MuJoCo is z-up, three.js is y-up: everything lives under one root turned -90° about x.
const world = new THREE.Group();
world.rotation.x = -Math.PI / 2;
scene.add(world);
const q = (w) => new THREE.Quaternion(w[1], w[2], w[3], w[0]);   // MuJoCo (w,x,y,z) -> three (x,y,z,w)

function geometry(g) {
  const s = g.size;
  switch (g.type) {
    case "plane": { const geo = new THREE.PlaneGeometry(2 * (s[0] || 30), 2 * (s[1] || 30)); return geo; }
    case "box": return new THREE.BoxGeometry(2 * s[0], 2 * s[1], 2 * s[2]);
    case "sphere": return new THREE.SphereGeometry(s[0], 24, 16);
    case "ellipsoid": { const geo = new THREE.SphereGeometry(1, 24, 16); geo.scale(s[0], s[1], s[2]); return geo; }
    case "capsule": { const geo = new THREE.CapsuleGeometry(s[0], 2 * s[1], 6, 16); geo.rotateX(Math.PI / 2); return geo; }
    case "cylinder": { const geo = new THREE.CylinderGeometry(s[0], s[0], 2 * s[1], 24); geo.rotateX(Math.PI / 2); return geo; }
  }
  return null;
}

function buildScene(spec) {
  world.clear();
  const bodies = new Map();
  for (const g of spec.geoms) {
    const geo = geometry(g);
    if (!geo) continue;
    if (!bodies.has(g.body)) { const b = new THREE.Group(); world.add(b); bodies.set(g.body, b); }
    const [r, gr, b, a] = g.rgba;
    const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(r, gr, b), roughness: 0.75,
      transparent: a < 1, opacity: a });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.fromArray(g.pos);
    mesh.quaternion.copy(q(g.quat));
    mesh.castShadow = g.type !== "plane";
    mesh.receiveShadow = true;
    bodies.get(g.body).add(mesh);
  }
  return bodies;
}

// ---- data ----
const [models, replays] = await Promise.all([getJSON("data/model.json"), getJSON("data/replays.json")]);
if (!replays.length) fail("No replays in this build.");
for (const rp of replays) $("replay").add(new Option(`${rp.name}${rp.level ? ` · ${rp.level}` : ""}`, rp.name));

let rep = null, cur = {}, bodies = new Map(), frames = [], bodyIds = [], frame = 0, clock = 0, playing = true, follow = true;
const tmp = new THREE.Vector3(), focus = new THREE.Vector3();
let focusBody = null;   // the humanoid's root: the moving body with the most geoms under it

async function load(name) {
  rep = replays.find((r) => r.name === name);
  const data = await getJSON(`data/${name}.json`);
  bodies = buildScene(models[rep.xml]);
  cur = data; frames = data.frames; bodyIds = data.bodies;
  $("replay").value = name;
  const moving = bodyIds.filter((id, i) => frames.some((f) => [0, 1, 2].some((k) => Math.abs(f[i * 7 + k] - frames[0][i * 7 + k]) > 1e-3)));
  focusBody = moving.length ? moving.reduce((a, b) => (spec(b) > spec(a) ? b : a)) : null;
  $("scrub").max = frames.length - 1;
  $("now").textContent = `${rep.name} · ${rep.level || rep.mode}`;
  frame = 0; clock = 0; apply();
}
const spec = (body) => models[rep.xml].geoms.filter((g) => g.body === body).length;

function apply() {
  const f = frames[frame];   // per body, 7 numbers: x y z  qw qx qy qz
  bodyIds.forEach((id, i) => {
    const b = bodies.get(id);
    if (!b) return;
    const o = i * 7;
    b.position.set(f[o], f[o + 1], f[o + 2]);
    b.quaternion.set(f[o + 4], f[o + 5], f[o + 6], f[o + 3]);
  });
  $("scrub").value = frame;
  $("info").textContent = `${(frame * rep.frameTime).toFixed(2)} s · ${frame + 1}/${frames.length}`;
  infer(frame);
}

// ---- the policy, run in the browser on the recorded observation of the current control step ----
let ort = null, inferBusy = false, inferCount = 0, policyError = "", lastDiff = null;
const sessions = new Map(), latency = [];
function session(url) {
  if (!sessions.has(url)) {
    sessions.set(url, (async () => {
      if (!ort) { ort = await import("onnxruntime-web"); ort.env.wasm.numThreads = 1; }   // no SharedArrayBuffer needed
      return ort.InferenceSession.create(url, { executionProviders: ["wasm"] });
    })());
  }
  return sessions.get(url);
}
async function infer(i) {
  if (inferBusy || !rep?.policy || !cur.obs) return;
  inferBusy = true;
  const r = rep, obs = cur.obs[i], recorded = cur.action[i];
  try {
    const s = await session(r.policy);
    const t0 = performance.now();
    const out = await s.run({ obs: new ort.Tensor("float32", Float32Array.from(obs), [1, obs.length]) });
    const ms = performance.now() - t0;
    const a = out.action.data;
    let diff = 0;
    for (let k = 0; k < recorded.length; k++) diff = Math.max(diff, Math.abs(a[k] - recorded[k]));
    latency.push(ms); if (latency.length > 60) latency.shift();
    lastDiff = diff; policyError = ""; inferCount++;
    if (inferCount === 1 || inferCount % 500 === 0) {
      console.info(`[policy] ${r.policy} inference in the browser (onnxruntime-web, wasm): obs[1,${obs.length}] -> ` +
        `action[1,${a.length}] in ${ms.toFixed(2)} ms, max |action - recorded| = ${diff.toExponential(1)} ` +
        `(step ${i}, ${inferCount} inferences)`);
    }
  } catch (e) {
    policyError = String(e.message || e);
    console.warn(`[policy] ${r.policy}: ${policyError}`);
  } finally { inferBusy = false; }
}

// ---- diagnostics overlay (Tab or the corner "i"): FPS, episode reward, inference latency, stage ----
let fpsFrames = 0, fpsT0 = performance.now(), fps = 0;
function toggleOverlay() {
  const o = $("overlay"), open = o.hidden;
  o.hidden = !open; $("overlayBtn").setAttribute("aria-expanded", open);
}
function updateOverlay() {
  if ($("overlay").hidden) return;
  const avg = latency.length ? latency.reduce((x, y) => x + y, 0) / latency.length : null;
  $("ov-fps").textContent = fps.toFixed(0);
  $("ov-reward").textContent = "n/a: replays record no reward";
  $("ov-latency").textContent = !rep?.policy ? "no policy (random actions)"
    : policyError ? `error: ${policyError}` : avg == null ? "loading…" : `${avg.toFixed(2)} ms (avg of ${latency.length})`;
  $("ov-check").textContent = lastDiff == null || !rep?.policy ? "—" : lastDiff.toExponential(1);
  $("ov-stage").textContent = `${rep?.level || "—"} · ${rep?.mode || ""}`;
  $("ov-mode").textContent = idle.active ? "Demo (30 s idle)" : "Manual";
}

// ---- controls ----
$("replay").onchange = (e) => load(e.target.value);
$("play").onclick = () => { playing = !playing; $("play").textContent = playing ? "Pause" : "Play"; };
$("follow").onclick = () => { follow = !follow; $("follow").setAttribute("aria-pressed", follow); $("follow").textContent = follow ? "Follow" : "Free"; };
$("scrub").oninput = (e) => { frame = +e.target.value; clock = frame * rep.frameTime; apply(); };
addEventListener("keydown", (e) => {
  if (e.code === "Space") { e.preventDefault(); $("play").click(); }
  if (e.code === "Tab") { e.preventDefault(); toggleOverlay(); }
});
$("overlayBtn").onclick = toggleOverlay;

// ---- demo mode: after 30 s without input the policy replays cycle with an orbiting camera; any input stops it ----
const idle = new IdleTimer();
let dwell = 0;
function anyInput() {
  if (idle.input()) { document.body.classList.remove("demo"); controls.autoRotate = false; }
}
for (const ev of ["keydown", "pointerdown", "wheel", "touchstart"]) addEventListener(ev, anyInput, { capture: true, passive: true });
function gamepadInput() {
  for (const g of navigator.getGamepads?.() || []) if (g && (g.buttons.some((b) => b.pressed) || g.axes.some((a) => Math.abs(a) > 0.3))) return true;
  return false;
}
function demoStep(rawDt, dt) {
  if (gamepadInput()) anyInput();
  if (idle.tick(rawDt)) {
    document.body.classList.add("demo"); controls.autoRotate = true; controls.autoRotateSpeed = 1.2;
    playing = true; $("play").textContent = "Pause"; follow = true; dwell = 0;
  }
  if (!idle.active) return;
  dwell += dt;
  if (dwell >= DWELL_SECONDS) {
    dwell = 0;
    const list = replays.filter((r) => r.policy);
    if (list.length) load(list[(list.indexOf(rep) + 1) % list.length].name);
  }
}

// The canvas fills the viewport area between the page's top bar and footer (any aspect, landscape or portrait).
function resize() {
  const v = $("view"), w = Math.max(1, v.clientWidth), h = Math.max(1, v.clientHeight);
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe($("view")); resize();

await load(replays[0].name);
let last = performance.now();
renderer.setAnimationLoop((now) => {
  // rAF's timestamp is the frame's start, which can be earlier than the performance.now() taken above:
  // clamp so the first dt is never negative (a negative clock gave frame -1 and frames[-1] undefined).
  const rawDt = (now - last) / 1000;
  const dt = Math.max(0, Math.min(0.1, rawDt)); last = now;
  demoStep(rawDt, dt);
  fpsFrames++;
  if (now - fpsT0 >= 500) { fps = (fpsFrames * 1000) / (now - fpsT0); fpsFrames = 0; fpsT0 = now; updateOverlay(); }
  if (playing && frames.length) {
    clock += dt * +$("speed").value;
    const total = frames.length * rep.frameTime;
    if (clock >= total) clock %= total;
    if (clock < 0) clock = 0;
    const next = Math.max(0, Math.min(frames.length - 1, Math.floor(clock / rep.frameTime)));
    if (next !== frame) { frame = next; apply(); }
  }
  if (follow && focusBody != null && bodies.get(focusBody)) {
    bodies.get(focusBody).getWorldPosition(tmp);
    focus.lerp(tmp, 0.08);
    const delta = focus.clone().sub(controls.target);
    controls.target.add(delta); camera.position.add(delta);
  }
  controls.update();
  renderer.render(scene, camera);
});
