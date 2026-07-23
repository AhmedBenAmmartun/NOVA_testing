import {
  PAGE_COUNT,
  SAFE_AREA,
  WINDOW_MIN_SIZE,
  clampRect,
  cloneLayout,
  denormalizeRect,
  getSnapTarget,
  getWindowRectForTarget,
  normalizeRect,
  pageStorageKey,
  parseSavedLayout,
  resizeRect,
} from './layout-engine.js'

const PAGE_NAMES = ['Dashboard', 'NOVA + Second Brain', 'Apps & Files', 'Calendar', 'Agent Control']
const RESIZE_DIRECTIONS = ['n', 'e', 's', 'w', 'ne', 'nw', 'se', 'sw']
const MAX_UNDO_STEPS = 30

class NovaDashboardEnhancements {
  constructor() {
    this.root = null
    this.editMode = false
    this.currentPage = 0
    this.layouts = new Map()
    this.history = new Map()
    this.pointerOperation = null
    this.windowOperation = null
    this.windowLayouts = new Map()
    this.windowZ = 100
    this.refreshQueued = false
    this.saveTimer = null
    this.hiddenMenuOpen = false
    this.boundRoots = new WeakSet()
    this.desktopMode = document.documentElement.classList.contains('nova-desktop-mode')
  }

  init() {
    this.root = document.querySelector('[data-screen-label="NOVA Desktop"]')
    if (!this.root) {
      window.setTimeout(() => this.init(), 50)
      return
    }

    this.restoreLayouts()
    this.createEditUi()
    this.createSnapPreview()
    this.bindEvents()
    this.refresh()

    this.observer = new MutationObserver(() => this.queueRefresh())
    this.observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style'],
      childList: true,
      subtree: true,
    })

    window.NOVADashboard = Object.freeze({
      version: '2.0.0',
      contractVersion: window.NOVAIntegration?.contractVersion ?? '1.0.0',
      getMode: () => window.NOVAIntegration?.getState().mode ?? 'demo',
      getCurrentPage: () => this.currentPage,
      getLayout: (page = this.currentPage) => cloneLayout(this.layouts.get(page) ?? null),
      resetCurrentPage: () => this.resetCurrentPage(),
      resetAllPages: () => this.resetAllPages(),
      setEditMode: (enabled) => this.setEditMode(Boolean(enabled)),
    })
  }

  restoreLayouts() {
    for (let page = 0; page < PAGE_COUNT; page += 1) {
      const primary = localStorage.getItem(pageStorageKey(page))
      const legacyDesktop = page === 0 ? localStorage.getItem('nova.desktop.layout.v1') : null
      const saved = parseSavedLayout(primary || legacyDesktop)
      if (saved) this.layouts.set(page, saved)
    }
  }

  createEditUi() {
    this.editButton = document.createElement('button')
    this.editButton.type = 'button'
    this.editButton.className = 'nova-edit-trigger'
    this.editButton.setAttribute('aria-pressed', 'false')
    this.editButton.setAttribute('aria-label', 'Edit current page layout')
    this.editButton.innerHTML = '<span class="nova-edit-trigger-dot"></span><span>Edit layout</span>'

    this.toolbar = document.createElement('div')
    this.toolbar.className = 'nova-layout-toolbar'
    this.toolbar.dataset.open = 'false'
    this.toolbar.setAttribute('role', 'toolbar')
    this.toolbar.setAttribute('aria-label', 'Layout editing controls')
    this.toolbar.innerHTML = `
      <span class="nova-layout-toolbar-title"></span>
      <button type="button" data-layout-action="undo">Undo</button>
      <button type="button" data-layout-action="hidden">Hidden (0)</button>
      <button type="button" data-layout-action="reset-page">Reset Current Page</button>
      <button type="button" data-layout-action="reset-all">Reset All Pages</button>
      <span class="nova-layout-saved" aria-live="polite">Saved</span>
      <button type="button" data-layout-action="done">Done</button>
    `

    this.hiddenMenu = document.createElement('div')
    this.hiddenMenu.className = 'nova-hidden-menu'
    this.hiddenMenu.dataset.open = 'false'
    this.hiddenMenu.setAttribute('aria-label', 'Hidden cards')

    this.root.append(this.editButton, this.toolbar, this.hiddenMenu)
  }

  createSnapPreview() {
    this.snapPreview = document.createElement('div')
    this.snapPreview.className = 'nova-window-snap-preview'
    this.snapPreview.dataset.open = 'false'
    this.root.append(this.snapPreview)
  }

  bindEvents() {
    this.editButton.addEventListener('click', () => this.setEditMode(!this.editMode))
    this.toolbar.addEventListener('click', (event) => this.onToolbarClick(event))
    this.hiddenMenu.addEventListener('click', (event) => this.onHiddenMenuClick(event))
    this.bindRootEvents(this.root)
    window.addEventListener('pointermove', (event) => this.onPointerMove(event))
    window.addEventListener('pointerup', (event) => this.onPointerUp(event))
    window.addEventListener('pointercancel', (event) => this.onPointerUp(event))
    window.addEventListener('resize', () => this.onResize())
    window.addEventListener('nova:desktop-mode', (event) => this.onDesktopMode(Boolean(event.detail?.active)))
    document.addEventListener('keydown', (event) => this.onKeyDown(event), true)
  }

  bindRootEvents(root) {
    if (this.boundRoots.has(root)) return
    this.boundRoots.add(root)
    root.addEventListener('click', (event) => this.onRootClick(event), true)
    root.addEventListener('click', () => window.setTimeout(() => this.queueRefresh(), 560), true)
    root.addEventListener('pointerdown', (event) => this.onPointerDown(event), true)
    root.addEventListener('mousedown', (event) => this.blockManagedMouseDown(event), true)
  }

  queueRefresh() {
    if (this.refreshQueued) return
    this.refreshQueued = true
    requestAnimationFrame(() => {
      this.refreshQueued = false
      this.refresh()
    })
  }

  refresh() {
    const liveRoot = document.querySelector('[data-screen-label="NOVA Desktop"]')
    if (!liveRoot) return
    if (liveRoot !== this.root) {
      this.root = liveRoot
      this.bindRootEvents(liveRoot)
    }
    for (const element of [this.editButton, this.toolbar, this.hiddenMenu, this.snapPreview]) {
      if (element && element.parentElement !== liveRoot) liveRoot.append(element)
    }
    liveRoot.classList.toggle('nova-editing', this.editMode)

    const nextPage = this.detectCurrentPage()
    if (nextPage !== this.currentPage) {
      this.currentPage = nextPage
      this.hiddenMenuOpen = false
      this.hiddenMenu.dataset.open = 'false'
    }

    for (let page = 0; page < PAGE_COUNT; page += 1) {
      const canvas = this.getCanvas(page)
      if (!canvas) continue
      this.installCardControls(canvas)
      if (this.layouts.has(page)) this.applyLayout(page)
    }

    this.installWindowControls()
    this.updateToolbar()
  }

  storageKey(page) {
    return pageStorageKey(page)
  }

  onDesktopMode(active) {
    this.desktopMode = Boolean(active)
    this.currentPage = this.detectCurrentPage()
    this.refresh()
  }

  detectCurrentPage() {
    const shells = [...this.root.querySelectorAll('[data-page-shell]')]
    const active = shells.find((shell) => getComputedStyle(shell).zIndex === '2')
    const page = Number(active?.dataset.pageShell)
    return Number.isInteger(page) ? page : this.currentPage
  }

  getCanvas(page = this.currentPage) {
    return this.root.querySelector(`[data-page-canvas="${page}"]`)
  }

  getCards(page = this.currentPage) {
    return [...(this.getCanvas(page)?.querySelectorAll('[data-layout-card]') ?? [])]
  }

  setEditMode(enabled) {
    this.refresh()
    this.currentPage = this.detectCurrentPage()
    if (enabled) this.ensureLayout(this.currentPage)
    this.editMode = enabled
    this.root.classList.toggle('nova-editing', enabled)
    this.editButton.setAttribute('aria-pressed', String(enabled))
    this.editButton.lastElementChild.textContent = enabled ? 'Editing' : 'Edit layout'
    this.toolbar.dataset.open = String(enabled)
    window.dispatchEvent(new CustomEvent('nova:layout-edit', { detail: { editing: enabled } }))
    if (!enabled) {
      this.hiddenMenuOpen = false
      this.hiddenMenu.dataset.open = 'false'
    }
    this.updateToolbar()
  }

  ensureLayout(page) {
    if (this.layouts.has(page)) return this.layouts.get(page)
    const canvas = this.getCanvas(page)
    if (!canvas) return null
    const canvasRect = canvas.getBoundingClientRect()
    const cards = {}

    for (const card of this.getCards(page)) {
      const rect = card.getBoundingClientRect()
      cards[card.dataset.layoutCard] = {
        ...normalizeRect({
          x: rect.left - canvasRect.left,
          y: rect.top - canvasRect.top,
          width: rect.width,
          height: rect.height,
        }, canvasRect),
        title: card.dataset.cardTitle || card.dataset.layoutCard,
        pinned: false,
        hidden: false,
      }
    }

    const layout = { version: 2, page, savedAt: new Date().toISOString(), cards }
    this.layouts.set(page, layout)
    this.saveLayout(page)
    this.applyLayout(page)
    return layout
  }

  applyLayout(page) {
    const canvas = this.getCanvas(page)
    const layout = this.layouts.get(page)
    if (!canvas || !layout) return
    const bounds = canvas.getBoundingClientRect()
    canvas.classList.add('nova-has-custom-layout')

    for (const card of this.getCards(page)) {
      const id = card.dataset.layoutCard
      let item = layout.cards[id]
      if (!item) {
        const offset = Object.keys(layout.cards).length % 6
        const fallback = clampRect({
          x: SAFE_AREA.left + offset * 24,
          y: SAFE_AREA.top + offset * 22,
          width: Math.min(340, bounds.width * 0.3),
          height: Math.min(230, bounds.height * 0.28),
        }, bounds)
        item = {
          ...normalizeRect(fallback, bounds),
          title: card.dataset.cardTitle || id,
          pinned: false,
          hidden: false,
        }
        layout.cards[id] = item
        this.saveLayout(page)
      }

      const rect = clampRect(denormalizeRect(item, bounds), bounds)
      this.applyCardPixels(card, rect)
      card.dataset.cardPinned = String(Boolean(item.pinned))
      card.dataset.cardHidden = String(Boolean(item.hidden))
    }
  }

  installCardControls(canvas) {
    for (const card of canvas.querySelectorAll('[data-layout-card]')) {
      if (card.querySelector(':scope > .nova-layout-card-controls')) continue

      const controls = document.createElement('div')
      controls.className = 'nova-layout-card-controls'
      controls.innerHTML = `
        <button type="button" class="nova-card-pin" data-card-action="pin" title="Pin or unpin card" aria-label="Pin or unpin card">◆</button>
        <button type="button" data-card-action="hide" title="Hide card" aria-label="Hide card">—</button>
      `

      const dragHandle = document.createElement('div')
      dragHandle.className = 'nova-card-drag-handle'
      dragHandle.dataset.cardAction = 'drag'
      dragHandle.setAttribute('aria-hidden', 'true')

      card.append(dragHandle, controls)
      for (const direction of RESIZE_DIRECTIONS) {
        const handle = document.createElement('div')
        handle.className = 'nova-resize-handle'
        handle.dataset.cardAction = 'resize'
        handle.dataset.direction = direction
        handle.setAttribute('aria-hidden', 'true')
        card.append(handle)
      }
    }
  }

  onToolbarClick(event) {
    const action = event.target.closest('[data-layout-action]')?.dataset.layoutAction
    if (!action) return
    event.preventDefault()
    event.stopPropagation()

    if (action === 'undo') this.undo()
    if (action === 'hidden') this.toggleHiddenMenu()
    if (action === 'reset-page') this.resetCurrentPage()
    if (action === 'reset-all') this.resetAllPages()
    if (action === 'done') this.setEditMode(false)
  }

  onRootClick(event) {
    const windowAction = event.target.closest('[data-window-action]')
    if (windowAction) {
      const windowElement = windowAction.closest('[data-app-window]')
      if (windowElement && ['maximize', 'snap-left', 'snap-right'].includes(windowAction.dataset.windowAction)) {
        event.preventDefault()
        event.stopPropagation()
        event.stopImmediatePropagation()
        this.applyWindowAction(windowElement, windowAction.dataset.windowAction)
        return
      }
    }

    if (!this.editMode) return
    const button = event.target.closest('[data-card-action]')
    const card = button?.closest('[data-layout-card]')
    if (!button || !card) return
    const action = button.dataset.cardAction
    if (!['pin', 'hide'].includes(action)) return
    event.preventDefault()
    event.stopPropagation()
    event.stopImmediatePropagation()
    this.mutateCard(card, action)
  }

  mutateCard(card, action) {
    const page = Number(card.closest('[data-page-canvas]')?.dataset.pageCanvas)
    const layout = this.ensureLayout(page)
    const item = layout?.cards[card.dataset.layoutCard]
    if (!item) return
    this.pushUndo(page)
    if (action === 'pin') item.pinned = !item.pinned
    if (action === 'hide' && !item.pinned) item.hidden = true
    this.saveLayout(page)
    this.applyLayout(page)
    this.updateToolbar()
  }

  toggleHiddenMenu() {
    this.hiddenMenuOpen = !this.hiddenMenuOpen
    this.hiddenMenu.dataset.open = String(this.hiddenMenuOpen)
    this.renderHiddenMenu()
  }

  renderHiddenMenu() {
    const layout = this.layouts.get(this.currentPage)
    const hidden = Object.entries(layout?.cards ?? {}).filter(([, item]) => item.hidden)
    if (hidden.length === 0) {
      this.hiddenMenu.innerHTML = '<div class="nova-hidden-menu-empty">No hidden cards on this page.</div>'
      return
    }

    this.hiddenMenu.innerHTML = hidden.map(([id, item]) => (
      `<button type="button" data-restore-card="${this.escapeHtml(id)}">Restore ${this.escapeHtml(item.title || id)}</button>`
    )).join('')
  }

  onHiddenMenuClick(event) {
    const button = event.target.closest('[data-restore-card]')
    if (!button) return
    event.preventDefault()
    event.stopPropagation()
    const layout = this.layouts.get(this.currentPage)
    const item = layout?.cards[button.dataset.restoreCard]
    if (!item) return
    this.pushUndo(this.currentPage)
    item.hidden = false
    this.saveLayout(this.currentPage)
    this.applyLayout(this.currentPage)
    this.renderHiddenMenu()
    this.updateToolbar()
  }

  onPointerDown(event) {
    const resizeHandle = event.target.closest('.nova-resize-handle')
    const dragHandle = event.target.closest('.nova-card-drag-handle')
    if (this.editMode && (resizeHandle || dragHandle)) {
      const card = event.target.closest('[data-layout-card]')
      if (card?.dataset.cardPinned === 'true') return
      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()
      this.beginCardOperation(card, resizeHandle ? 'resize' : 'drag', resizeHandle?.dataset.direction, event)
      return
    }

    const windowElement = event.target.closest('[data-app-window]')
    if (!windowElement) return
    this.raiseWindow(windowElement)
    const windowResize = event.target.closest('.nova-window-resize-handle')
    const titlebar = event.target.closest('[data-app-window-titlebar]')
    if (!windowResize && (!titlebar || event.target.closest('button'))) return
    event.preventDefault()
    event.stopPropagation()
    event.stopImmediatePropagation()
    this.beginWindowOperation(windowElement, windowResize ? 'resize' : 'drag', event)
  }

  blockManagedMouseDown(event) {
    const cardControl = event.target.closest('.nova-card-drag-handle, .nova-resize-handle, .nova-layout-card-controls')
    const windowControl = event.target.closest('.nova-window-resize-handle, [data-app-window-titlebar]')
    if ((this.editMode && cardControl) || (windowControl && !event.target.closest('button'))) {
      event.preventDefault()
      event.stopPropagation()
      event.stopImmediatePropagation()
    }
  }

  beginCardOperation(card, type, direction, event) {
    const page = Number(card.closest('[data-page-canvas]')?.dataset.pageCanvas)
    const canvas = this.getCanvas(page)
    const layout = this.ensureLayout(page)
    if (!canvas || !layout) return
    const canvasRect = canvas.getBoundingClientRect()
    const cardRect = card.getBoundingClientRect()
    this.pushUndo(page)
    this.pointerOperation = {
      type,
      direction,
      card,
      page,
      canvas,
      canvasRect,
      startX: event.clientX,
      startY: event.clientY,
      startRect: {
        x: cardRect.left - canvasRect.left,
        y: cardRect.top - canvasRect.top,
        width: cardRect.width,
        height: cardRect.height,
      },
    }
    card.setPointerCapture?.(event.pointerId)
  }

  onPointerMove(event) {
    if (this.pointerOperation) {
      event.preventDefault()
      const operation = this.pointerOperation
      const deltaX = event.clientX - operation.startX
      const deltaY = event.clientY - operation.startY
      const candidate = operation.type === 'drag'
        ? { ...operation.startRect, x: operation.startRect.x + deltaX, y: operation.startRect.y + deltaY }
        : resizeRect(operation.startRect, operation.direction, deltaX, deltaY)
      const rect = clampRect(candidate, operation.canvasRect)
      this.updateCardRect(operation.page, operation.card.dataset.layoutCard, rect, operation.canvasRect)
      this.applyCardPixels(operation.card, rect)
      return
    }

    if (this.windowOperation) this.moveWindowOperation(event)
  }

  onPointerUp(event) {
    if (this.pointerOperation) {
      const page = this.pointerOperation.page
      this.pointerOperation = null
      this.saveLayout(page)
      this.updateToolbar()
    }

    if (this.windowOperation) this.endWindowOperation(event)
  }

  updateCardRect(page, id, rect, bounds) {
    const layout = this.layouts.get(page)
    const item = layout?.cards[id]
    if (!item) return
    Object.assign(item, normalizeRect(rect, bounds))
    layout.savedAt = new Date().toISOString()
  }

  applyCardPixels(card, rect) {
    this.setCustomProperty(card, '--nova-card-x', `${rect.x}px`)
    this.setCustomProperty(card, '--nova-card-y', `${rect.y}px`)
    this.setCustomProperty(card, '--nova-card-w', `${rect.width}px`)
    this.setCustomProperty(card, '--nova-card-h', `${rect.height}px`)
  }

  setCustomProperty(element, property, value) {
    if (element.style.getPropertyValue(property) !== value) element.style.setProperty(property, value)
  }

  pushUndo(page) {
    const layout = this.layouts.get(page)
    if (!layout) return
    const stack = this.history.get(page) ?? []
    stack.push(cloneLayout(layout))
    if (stack.length > MAX_UNDO_STEPS) stack.shift()
    this.history.set(page, stack)
  }

  undo() {
    const stack = this.history.get(this.currentPage) ?? []
    const previous = stack.pop()
    if (!previous) return
    this.layouts.set(this.currentPage, previous)
    this.history.set(this.currentPage, stack)
    this.saveLayout(this.currentPage)
    this.applyLayout(this.currentPage)
    this.updateToolbar()
  }

  resetCurrentPage() {
    const page = this.currentPage
    if (this.layouts.has(page)) this.pushUndo(page)
    this.layouts.delete(page)
    localStorage.removeItem(this.storageKey(page))
    this.clearPageStyles(page)
    this.signalSaved('Reset')
    this.updateToolbar()
  }

  resetAllPages() {
    for (let page = 0; page < PAGE_COUNT; page += 1) {
      localStorage.removeItem(pageStorageKey(page))
      this.clearPageStyles(page)
    }
    localStorage.removeItem('nova.desktop.layout.v1')
    this.layouts.clear()
    this.history.clear()
    this.hiddenMenuOpen = false
    this.hiddenMenu.dataset.open = 'false'
    this.signalSaved('Reset all')
    this.updateToolbar()
  }

  clearPageStyles(page) {
    const canvas = this.getCanvas(page)
    canvas?.classList.remove('nova-has-custom-layout')
    for (const card of this.getCards(page)) {
      card.style.removeProperty('--nova-card-x')
      card.style.removeProperty('--nova-card-y')
      card.style.removeProperty('--nova-card-w')
      card.style.removeProperty('--nova-card-h')
      delete card.dataset.cardPinned
      delete card.dataset.cardHidden
    }
  }

  saveLayout(page) {
    const layout = this.layouts.get(page)
    if (!layout) return
    layout.savedAt = new Date().toISOString()
    localStorage.setItem(this.storageKey(page), JSON.stringify(layout))
    this.signalSaved('Saved')
  }

  signalSaved(message) {
    if (!this.toolbar) return
    const status = this.toolbar.querySelector('.nova-layout-saved')
    status.textContent = message
    window.clearTimeout(this.saveTimer)
    this.saveTimer = window.setTimeout(() => {
      status.textContent = 'Saved'
    }, 1200)
  }

  updateToolbar() {
    if (!this.toolbar) return
    const layout = this.layouts.get(this.currentPage)
    const hiddenCount = Object.values(layout?.cards ?? {}).filter((item) => item.hidden).length
    this.toolbar.querySelector('.nova-layout-toolbar-title').textContent = PAGE_NAMES[this.currentPage]
    this.toolbar.querySelector('[data-layout-action="undo"]').disabled = (this.history.get(this.currentPage)?.length ?? 0) === 0
    this.toolbar.querySelector('[data-layout-action="hidden"]').textContent = `Hidden (${hiddenCount})`
    if (this.hiddenMenuOpen) this.renderHiddenMenu()
  }

  installWindowControls() {
    for (const windowElement of this.root.querySelectorAll('[data-app-window]')) {
      const id = windowElement.dataset.appWindow
      if (!this.windowLayouts.has(id)) {
        const rect = windowElement.getBoundingClientRect()
        const geometry = clampRect({
          x: rect.left,
          y: rect.top,
          width: rect.width || 640,
          height: rect.height || 420,
        }, { width: window.innerWidth, height: window.innerHeight }, { top: 66, right: 16, bottom: 96, left: 16 }, WINDOW_MIN_SIZE)
        this.windowLayouts.set(id, { geometry, restore: null, mode: 'free' })
      }

      windowElement.classList.add('nova-window-managed')
      if (!windowElement.querySelector(':scope > .nova-window-resize-handle')) {
        const handle = document.createElement('div')
        handle.className = 'nova-window-resize-handle'
        handle.setAttribute('aria-hidden', 'true')
        windowElement.append(handle)
      }
      this.applyWindowGeometry(windowElement, this.windowLayouts.get(id).geometry)
    }
  }

  raiseWindow(windowElement) {
    this.windowZ += 1
    windowElement.style.setProperty('z-index', String(this.windowZ), 'important')
  }

  beginWindowOperation(windowElement, type, event) {
    const state = this.windowLayouts.get(windowElement.dataset.appWindow)
    if (!state) return
    if (state.mode !== 'free') {
      const pointerRatio = (event.clientX - state.geometry.x) / Math.max(1, state.geometry.width)
      const restore = state.restore ?? { x: event.clientX - 320, y: 90, width: 640, height: 420 }
      state.geometry = {
        ...restore,
        x: event.clientX - restore.width * pointerRatio,
        y: Math.max(66, event.clientY - 18),
      }
      state.mode = 'free'
      this.applyWindowGeometry(windowElement, state.geometry)
    }

    this.windowOperation = {
      type,
      windowElement,
      state,
      startX: event.clientX,
      startY: event.clientY,
      startRect: { ...state.geometry },
      snapTarget: null,
    }
  }

  moveWindowOperation(event) {
    event.preventDefault()
    const operation = this.windowOperation
    const deltaX = event.clientX - operation.startX
    const deltaY = event.clientY - operation.startY
    const viewport = { width: window.innerWidth, height: window.innerHeight }
    const safe = { top: 66, right: 16, bottom: 96, left: 16 }
    const candidate = operation.type === 'drag'
      ? { ...operation.startRect, x: operation.startRect.x + deltaX, y: operation.startRect.y + deltaY }
      : { ...operation.startRect, width: operation.startRect.width + deltaX, height: operation.startRect.height + deltaY }
    operation.state.geometry = clampRect(candidate, viewport, safe, WINDOW_MIN_SIZE)
    operation.state.mode = 'free'
    this.applyWindowGeometry(operation.windowElement, operation.state.geometry)

    operation.snapTarget = operation.type === 'drag'
      ? getSnapTarget(event.clientX, event.clientY, viewport.width)
      : null
    this.showSnapPreview(operation.snapTarget)
  }

  endWindowOperation() {
    const operation = this.windowOperation
    this.windowOperation = null
    this.showSnapPreview(null)
    if (operation.snapTarget) this.setWindowTarget(operation.windowElement, operation.snapTarget)
  }

  applyWindowAction(windowElement, action) {
    const target = action === 'snap-left' ? 'left' : action === 'snap-right' ? 'right' : 'maximize'
    const state = this.windowLayouts.get(windowElement.dataset.appWindow)
    if (!state) return
    if (state.mode === target && state.restore) {
      state.geometry = state.restore
      state.restore = null
      state.mode = 'free'
      this.applyWindowGeometry(windowElement, state.geometry)
      return
    }
    this.setWindowTarget(windowElement, target)
  }

  setWindowTarget(windowElement, target) {
    const state = this.windowLayouts.get(windowElement.dataset.appWindow)
    if (!state) return
    if (state.mode === 'free') state.restore = { ...state.geometry }
    state.geometry = getWindowRectForTarget(target, { width: window.innerWidth, height: window.innerHeight })
    state.mode = target
    this.applyWindowGeometry(windowElement, state.geometry)
  }

  applyWindowGeometry(windowElement, geometry) {
    this.setCustomProperty(windowElement, '--nova-window-x', `${geometry.x}px`)
    this.setCustomProperty(windowElement, '--nova-window-y', `${geometry.y}px`)
    this.setCustomProperty(windowElement, '--nova-window-w', `${geometry.width}px`)
    this.setCustomProperty(windowElement, '--nova-window-h', `${geometry.height}px`)
  }

  showSnapPreview(target) {
    if (!target) {
      this.snapPreview.dataset.open = 'false'
      return
    }
    const rect = getWindowRectForTarget(target, { width: window.innerWidth, height: window.innerHeight })
    Object.assign(this.snapPreview.style, {
      left: `${rect.x}px`,
      top: `${rect.y}px`,
      width: `${rect.width}px`,
      height: `${rect.height}px`,
    })
    this.snapPreview.dataset.open = 'true'
  }

  onResize() {
    for (let page = 0; page < PAGE_COUNT; page += 1) {
      if (this.layouts.has(page)) this.applyLayout(page)
    }
    for (const windowElement of this.root.querySelectorAll('[data-app-window]')) {
      const state = this.windowLayouts.get(windowElement.dataset.appWindow)
      if (!state) continue
      if (state.mode === 'free') {
        state.geometry = clampRect(state.geometry, { width: window.innerWidth, height: window.innerHeight }, { top: 66, right: 16, bottom: 96, left: 16 }, WINDOW_MIN_SIZE)
      } else {
        state.geometry = getWindowRectForTarget(state.mode, { width: window.innerWidth, height: window.innerHeight })
      }
      this.applyWindowGeometry(windowElement, state.geometry)
    }
  }

  onKeyDown(event) {
    if (!this.editMode) return
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
      event.preventDefault()
      event.stopPropagation()
      this.undo()
    }
  }

  escapeHtml(value) {
    return String(value)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;')
  }
}

function startEnhancements() {
  const enhancements = new NovaDashboardEnhancements()
  enhancements.init()
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startEnhancements, { once: true })
} else {
  startEnhancements()
}
