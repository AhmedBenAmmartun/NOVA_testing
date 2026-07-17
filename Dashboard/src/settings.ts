import type { DashboardSettings, WidgetInstance, ViewMode } from './types'

export const SETTINGS_VERSION = 1
const STORAGE_KEY = 'nova.desktopCompanion.settings.v1'

export const defaultWidgets: WidgetInstance[] = [
  { id: 'w-status', widgetId: 'nova-status', size: 'medium' },
  { id: 'w-priority', widgetId: 'current-priority', size: 'medium' },
  { id: 'w-tasks', widgetId: 'task-list', size: 'large' },
  { id: 'w-school', widgetId: 'school-assignments', size: 'large' },
  { id: 'w-memory', widgetId: 'obsidian-memory', size: 'medium' },
  { id: 'w-activity', widgetId: 'activity-feed', size: 'medium' },
]

export const defaultSettings: DashboardSettings = {
  version: SETTINGS_VERSION,
  mode: 'mini',
  theme: 'dark',
  pinned: true,
  activePage: 'home',
  widgets: defaultWidgets,
  onboarded: false,
}

function isViewMode(value: unknown): value is ViewMode {
  return value === 'orb' || value === 'mini' || value === 'compact' || value === 'full'
}

export function loadSettings(): DashboardSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return defaultSettings

    const parsed = JSON.parse(raw) as Partial<DashboardSettings>
    if (parsed.version !== SETTINGS_VERSION) return defaultSettings

    return {
      ...defaultSettings,
      ...parsed,
      mode: isViewMode(parsed.mode) ? parsed.mode : defaultSettings.mode,
      widgets: Array.isArray(parsed.widgets) ? parsed.widgets : defaultWidgets,
    }
  } catch {
    return defaultSettings
  }
}

export function saveSettings(settings: DashboardSettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
}

export function resetSettings(): DashboardSettings {
  localStorage.removeItem(STORAGE_KEY)
  return defaultSettings
}
