export const PAGE_COUNT = 5

export const SAFE_AREA = Object.freeze({
  top: 72,
  right: 34,
  bottom: 100,
  left: 34,
})

export const CARD_MIN_SIZE = Object.freeze({ width: 160, height: 96 })
export const WINDOW_MIN_SIZE = Object.freeze({ width: 320, height: 220 })

export function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum))
}

export function clampRect(rect, bounds, safeArea = SAFE_AREA, minSize = CARD_MIN_SIZE) {
  const availableWidth = Math.max(1, bounds.width - safeArea.left - safeArea.right)
  const availableHeight = Math.max(1, bounds.height - safeArea.top - safeArea.bottom)
  const width = clamp(rect.width, Math.min(minSize.width, availableWidth), availableWidth)
  const height = clamp(rect.height, Math.min(minSize.height, availableHeight), availableHeight)
  const x = clamp(rect.x, safeArea.left, bounds.width - safeArea.right - width)
  const y = clamp(rect.y, safeArea.top, bounds.height - safeArea.bottom - height)

  return { x, y, width, height }
}

export function normalizeRect(rect, bounds) {
  const width = Math.max(1, bounds.width)
  const height = Math.max(1, bounds.height)

  return {
    x: rect.x / width,
    y: rect.y / height,
    width: rect.width / width,
    height: rect.height / height,
  }
}

export function denormalizeRect(layout, bounds) {
  return {
    x: layout.x * bounds.width,
    y: layout.y * bounds.height,
    width: layout.width * bounds.width,
    height: layout.height * bounds.height,
  }
}

export function resizeRect(startRect, direction, deltaX, deltaY) {
  const next = { ...startRect }

  if (direction.includes('e')) next.width += deltaX
  if (direction.includes('s')) next.height += deltaY
  if (direction.includes('w')) {
    next.x += deltaX
    next.width -= deltaX
  }
  if (direction.includes('n')) {
    next.y += deltaY
    next.height -= deltaY
  }

  return next
}

export function pageStorageKey(pageIndex) {
  const page = clamp(Math.trunc(pageIndex), 0, PAGE_COUNT - 1)
  return `nova.desktop.layout.v2.page.${page}`
}

export function parseSavedLayout(value) {
  if (!value) return null

  try {
    const parsed = JSON.parse(value)
    if (!parsed || parsed.version !== 2 || !parsed.cards || typeof parsed.cards !== 'object') {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export function getSnapTarget(clientX, clientY, viewportWidth, threshold = 34) {
  if (clientY <= threshold) return 'maximize'
  if (clientX <= threshold) return 'left'
  if (clientX >= viewportWidth - threshold) return 'right'
  return null
}

export function getWindowRectForTarget(target, viewport) {
  const top = 66
  const bottom = 96
  const gutter = 16
  const height = Math.max(WINDOW_MIN_SIZE.height, viewport.height - top - bottom)

  if (target === 'maximize') {
    return {
      x: gutter,
      y: top,
      width: Math.max(WINDOW_MIN_SIZE.width, viewport.width - gutter * 2),
      height,
    }
  }

  const width = Math.max(WINDOW_MIN_SIZE.width, (viewport.width - gutter * 3) / 2)
  return {
    x: target === 'right' ? viewport.width - gutter - width : gutter,
    y: top,
    width,
    height,
  }
}

export function cloneLayout(layout) {
  return JSON.parse(JSON.stringify(layout))
}
