// node --test web/idle.test.mjs   (run by sim/tests/test_web_build.py)
import { test } from "node:test";
import assert from "node:assert/strict";
import { IdleTimer, IDLE_SECONDS, MAX_FRAME_SECONDS } from "./idle.js";

test("demo mode starts after 30 s of normal frames", () => {
  assert.equal(IDLE_SECONDS, 30);
  const t = new IdleTimer();
  let started = 0;
  for (let i = 0; i < 29.9 * 60; i++) started += t.tick(1 / 60);
  assert.equal(started, 0);
  for (let i = 0; i < 12; i++) started += t.tick(1 / 60);
  assert.equal(started, 1);
  assert.ok(t.active);
});

test("a long frame does not count as idle time", () => {
  assert.equal(MAX_FRAME_SECONDS, 0.25);
  const t = new IdleTimer();
  assert.equal(t.tick(10), false); // a 10 s hitch (tab in background, download)
  assert.equal(t.tick(0.26), false);
  assert.equal(t.idle, 0);
  for (let i = 0; i < 25 * 60; i++) t.tick(1 / 60);
  assert.equal(t.tick(40), false); // still not 30 s of real frames
  assert.equal(t.active, false);
  for (let i = 0; i < 6 * 60; i++) t.tick(1 / 60);
  assert.equal(t.active, true);
});

test("input resets the timer and ends demo mode", () => {
  const t = new IdleTimer();
  for (let i = 0; i < 31 * 60; i++) t.tick(1 / 60);
  assert.equal(t.active, true);
  assert.equal(t.input(), true);
  assert.equal(t.active, false);
  assert.equal(t.idle, 0);
  assert.equal(t.input(), false);
});
