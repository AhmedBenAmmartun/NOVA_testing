import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { resolve } from 'node:path'

import {
  createDesktopState,
  reduceDesktopState,
} from '../web/desktop-mode-state.js'

test('desktop workspace starts interactive', () => {
  assert.deepEqual(createDesktopState(), {
    mode: 'desktop',
    clickThrough: false,
    editing: false,
    resumeClickThrough: false,
  })
})

test('edit mode temporarily disables click-through and restores it', () => {
  const clickThrough = reduceDesktopState(createDesktopState(), { type: 'toggle-click-through' })
  const editing = reduceDesktopState(clickThrough, { type: 'set-editing', editing: true })
  assert.equal(editing.editing, true)
  assert.equal(editing.clickThrough, false)
  assert.equal(editing.resumeClickThrough, true)

  const locked = reduceDesktopState(editing, { type: 'set-editing', editing: false })
  assert.equal(locked.editing, false)
  assert.equal(locked.clickThrough, true)
})

test('dashboard events cannot leave the desktop workspace', () => {
  const initial = createDesktopState()
  for (const type of ['enter-dashboard', 'enter-desktop', 'toggle-mode']) {
    const next = reduceDesktopState(initial, { type })
    assert.equal(next.mode, 'desktop')
    assert.equal(next.clickThrough, false)
  }
})

test('click-through remains an explicit optional toggle', () => {
  const initial = createDesktopState()
  const enabled = reduceDesktopState(initial, { type: 'toggle-click-through' })
  assert.equal(enabled.clickThrough, true)
  assert.equal(reduceDesktopState(enabled, { type: 'toggle-click-through' }).clickThrough, false)
})

test('desktop shell keeps all five pages and global navigation interactive', async () => {
  const shell = await readFile(resolve('web/tauri-shell.js'), 'utf8')
  assert.doesNotMatch(shell, /\[data-nova-chrome\]\{display:none!important\}/)
  assert.doesNotMatch(shell, /\[data-page-shell\]\{display:none!important\}/)
  assert.doesNotMatch(shell, /data-page-shell="0"\]\{display:block!important/)
  assert.match(shell, /enter_desktop_mode/)
  assert.match(shell, /set_click_through/)
  assert.match(shell, /clickThrough: false|createDesktopState/)
})

test('all five pages keep independent persistent layouts', async () => {
  const enhancements = await readFile(resolve('web/dashboard-enhancements.js'), 'utf8')
  assert.match(enhancements, /return pageStorageKey\(page\)/)
  assert.doesNotMatch(enhancements, /if \(this\.desktopMode\) return 0/)
  assert.match(enhancements, /for \(let page = 0; page < PAGE_COUNT; page \+= 1\)/)
})
