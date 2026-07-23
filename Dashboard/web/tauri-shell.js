/* NOVA native shell: one interactive five-page desktop workspace. */
import { createDesktopState, reduceDesktopState } from './desktop-mode-state.js'

(function () {
  const underTauri = Boolean(window.__TAURI__) || location.protocol === 'tauri:' || location.hostname === 'tauri.localhost'
  if (!underTauri) return

  window.NOVA_BACKEND = '127.0.0.1:8787'
  const T = window.__TAURI__ || {}
  const invoke = T.core?.invoke ? T.core.invoke.bind(T.core) : () => Promise.resolve()
  const listen = T.event?.listen ? T.event.listen.bind(T.event) : () => Promise.resolve(() => {})
  let shellState = createDesktopState()

  function injectStyles() {
    const css = `
      html.nova-desktop-mode,html.nova-desktop-mode body{background:transparent!important}
      html.nova-desktop-mode [data-screen-label="NOVA Desktop"]{top:0!important;background:transparent!important;border:0!important;border-radius:0!important;box-shadow:none!important}
      html.nova-desktop-mode [data-screen-label="NOVA Desktop"]>img,
      html.nova-desktop-mode [data-screen-label="NOVA Desktop"]>div:nth-of-type(1),
      html.nova-desktop-mode [data-screen-label="NOVA Desktop"]>div:nth-of-type(2){display:none!important}
      html.nova-desktop-mode [data-page-track],
      html.nova-desktop-mode [data-page-shell],
      html.nova-desktop-mode [data-page-canvas]{background:transparent!important}
      html.nova-desktop-mode [data-nova-chrome]{pointer-events:auto}
      html.nova-desktop-mode:not(.nova-desktop-editing) .nova-layout-toolbar,
      html.nova-desktop-mode:not(.nova-desktop-editing) .nova-hidden-menu{display:none!important}
      html.nova-desktop-mode [data-layout-card]>[data-card-surface],
      html.nova-desktop-mode [data-layout-card][data-card-surface]{box-shadow:inset 0 1px rgba(255,255,255,.08),0 10px 30px rgba(0,0,0,.22)!important}
      #nova-deskbar{position:fixed;top:64px;right:14px;z-index:2147483001;display:none;gap:8px;padding:6px 8px;border-radius:12px;background:rgba(8,12,22,.82);backdrop-filter:blur(18px);border:1px solid rgba(255,255,255,.1)}
      html.nova-desktop-mode.nova-desktop-editing #nova-deskbar{display:flex}
      #nova-deskbar button{border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.05);color:rgba(234,240,246,.8);border-radius:8px;padding:5px 10px;font-size:11px;cursor:pointer}
      html.nova-click-through [data-screen-label="NOVA Desktop"],
      html.nova-click-through #nova-deskbar{pointer-events:none!important}
    `
    const el = document.createElement('style')
    el.textContent = css
    document.head.appendChild(el)
  }

  function buildDeskbar() {
    const bar = document.createElement('div')
    bar.id = 'nova-deskbar'
    const done = document.createElement('button')
    done.textContent = '✓ Done editing'
    done.addEventListener('click', () => window.NOVADashboard?.setEditMode(false))
    const reset = document.createElement('button')
    reset.textContent = 'Reset page'
    reset.addEventListener('click', () => window.NOVADashboard?.resetCurrentPage())
    bar.append(done, reset)
    document.body.append(bar)
  }

  function workArea() {
    const screenInfo = window.screen || {}
    return {
      x: typeof screenInfo.availLeft === 'number' ? screenInfo.availLeft : 0,
      y: typeof screenInfo.availTop === 'number' ? screenInfo.availTop : 0,
      w: screenInfo.availWidth || screenInfo.width || 1280,
      h: screenInfo.availHeight || screenInfo.height || 800,
    }
  }

  function applyState(previous) {
    const html = document.documentElement
    html.classList.add('nova-desktop-mode')
    html.classList.toggle('nova-desktop-editing', shellState.editing)
    html.classList.toggle('nova-click-through', shellState.clickThrough)
    try { localStorage.setItem('nova.mode', 'desktop') } catch (_error) {}

    const area = workArea()
    invoke('enter_desktop_mode', { x: area.x, y: area.y, w: area.w, h: area.h })
    invoke('set_click_through', { on: shellState.clickThrough })

    if (!previous) {
      window.dispatchEvent(new CustomEvent('nova:desktop-mode', { detail: { active: true } }))
    }
  }

  function transition(event) {
    const previous = shellState
    shellState = reduceDesktopState(shellState, event)
    applyState(previous)
  }

  function toggleEditMode() {
    const next = !shellState.editing
    if (window.NOVADashboard?.setEditMode) window.NOVADashboard.setEditMode(next)
    else window.setTimeout(() => window.NOVADashboard?.setEditMode(next), 150)
  }

  function boot() {
    document.documentElement.classList.add('nova-tauri', 'nova-desktop-mode')
    injectStyles()
    buildDeskbar()

    window.addEventListener('nova:layout-edit', event => transition({ type: 'set-editing', editing: Boolean(event.detail?.editing) }))

    listen('nova://enter-desktop', () => transition({ type: 'enter-desktop' }))
    listen('nova://enter-dashboard', () => transition({ type: 'enter-desktop' }))
    listen('nova://toggle-desktop', () => transition({ type: 'enter-desktop' }))
    listen('nova://toggle-edit', () => toggleEditMode())
    listen('nova://toggle-click-through', () => transition({ type: 'toggle-click-through' }))
    listen('nova://reconnect', () => {})

    window.addEventListener('keydown', event => {
      if (!(event.ctrlKey || event.metaKey) || !event.shiftKey) return
      const key = event.key.toLowerCase()
      if (key === 'd') {
        event.preventDefault()
        transition({ type: 'enter-desktop' })
        invoke('win_show')
      }
      if (key === 'e') { event.preventDefault(); toggleEditMode() }
      if (key === 't') { event.preventDefault(); transition({ type: 'toggle-click-through' }) }
    })

    window.setTimeout(() => applyState(null), 400)
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
