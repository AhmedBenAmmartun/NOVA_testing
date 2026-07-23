import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clampRect,
  denormalizeRect,
  getSnapTarget,
  getWindowRectForTarget,
  normalizeRect,
  pageStorageKey,
  parseSavedLayout,
  resizeRect,
} from '../web/layout-engine.js'

test('normalization preserves card geometry across a same-size canvas', () => {
  const bounds = { width: 1600, height: 900 }
  const rect = { x: 120, y: 90, width: 520, height: 280 }
  assert.deepEqual(denormalizeRect(normalizeRect(rect, bounds), bounds), rect)
})

test('clampRect keeps cards inside the NOVA safe canvas', () => {
  const result = clampRect(
    { x: -200, y: -100, width: 5000, height: 3000 },
    { width: 1280, height: 720 },
  )
  assert.deepEqual(result, { x: 34, y: 72, width: 1212, height: 548 })
})

test('resizeRect supports resizing from north-west', () => {
  assert.deepEqual(
    resizeRect({ x: 100, y: 100, width: 400, height: 300 }, 'nw', 40, 25),
    { x: 140, y: 125, width: 360, height: 275 },
  )
})

test('each page receives an independent persistent key', () => {
  const keys = new Set(Array.from({ length: 5 }, (_, page) => pageStorageKey(page)))
  assert.equal(keys.size, 5)
})

test('saved layouts reject malformed or old data', () => {
  assert.equal(parseSavedLayout('not json'), null)
  assert.equal(parseSavedLayout('{"version":1,"cards":{}}'), null)
  assert.equal(parseSavedLayout('{"version":2,"cards":{}}').version, 2)
})

test('window edge targets map to left, right, and maximize', () => {
  assert.equal(getSnapTarget(1, 200, 1280), 'left')
  assert.equal(getSnapTarget(1279, 200, 1280), 'right')
  assert.equal(getSnapTarget(640, 1, 1280), 'maximize')
})

test('maximized windows remain inside desktop chrome', () => {
  const rect = getWindowRectForTarget('maximize', { width: 1366, height: 768 })
  assert.deepEqual(rect, { x: 16, y: 66, width: 1334, height: 606 })
})
