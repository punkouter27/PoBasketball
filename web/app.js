// Replay viewer: draws the MuJoCo scene's primitive geoms and moves their bodies from the frames web/build.py baked.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

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

let rep = null, bodies = new Map(), frames = [], bodyIds = [], frame = 0, clock = 0, playing = true, follow = true;
const tmp = new THREE.Vector3(), focus = new THREE.Vector3();
let focusBody = null;   // the humanoid's root: the moving body with the most geoms under it

async function load(name) {
  rep = replays.find((r) => r.name === name);
  const data = await getJSON(`data/${name}.json`);
  bodies = buildScene(models[rep.xml]);
  frames = data.frames; bodyIds = data.bodies;
  const moving = bodyIds.filter((id, i) => frames.some((f) => [0, 1, 2].some((k) => Math.abs(f[i * 7 + k] - frames[0][i * 7 + k]) > 1e-3)));
  focusBody = moving.length ? moving.reduce((a, b) => (spec(b) > spec(a) ? b : a)) : null;
  $("scrub").max = frames.length - 1;
  $("title").textContent = `${rep.name} · ${rep.mode}`;
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
}

// ---- controls ----
$("replay").onchange = (e) => load(e.target.value);
$("play").onclick = () => { playing = !playing; $("play").textContent = playing ? "Pause" : "Play"; };
$("follow").onclick = () => { follow = !follow; $("follow").setAttribute("aria-pressed", follow); $("follow").textContent = follow ? "Follow" : "Free"; };
$("scrub").oninput = (e) => { frame = +e.target.value; clock = frame * rep.frameTime; apply(); };
addEventListener("keydown", (e) => { if (e.code === "Space") { e.preventDefault(); $("play").click(); } });

function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
}
addEventListener("resize", resize); resize();

await load(replays[0].name);
let last = performance.now();
renderer.setAnimationLoop((now) => {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  if (playing && frames.length) {
    clock += dt * +$("speed").value;
    const total = frames.length * rep.frameTime;
    if (clock >= total) clock %= total;
    const next = Math.min(frames.length - 1, Math.floor(clock / rep.frameTime));
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
