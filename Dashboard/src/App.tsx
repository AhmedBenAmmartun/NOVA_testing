import { useEffect, useMemo, useState } from 'react'
import { loadSettings, resetSettings, saveSettings } from './settings'
import { useNovaMockClient } from './novaClient'
import type { DashboardSettings, ViewMode, WidgetInstance, WidgetSize } from './types'
import { getCategoryLabel, getWidgetDefinition, widgetRegistry } from './widgetRegistry'

const modeLabels: Array<{ id: ViewMode; label: string; hint: string }> = [
  { id: 'orb', label: 'Orb', hint: 'Smallest always-on-top state' },
  { id: 'mini', label: 'Mini', hint: 'Default desktop companion' },
  { id: 'compact', label: 'Compact', hint: 'Focused widget stack' },
  { id: 'full', label: 'Full', hint: 'Command center workspace' },
]

const sizeOrder: WidgetSize[] = ['small', 'medium', 'large']

function nextSize(size: WidgetSize): WidgetSize {
  const current = sizeOrder.indexOf(size)
  return sizeOrder[(current + 1) % sizeOrder.length]
}

function makeWidgetInstance(widgetId: string): WidgetInstance {
  const definition = getWidgetDefinition(widgetId)
  return {
    id: crypto.randomUUID(),
    widgetId,
    size: definition?.defaultSize ?? 'medium',
  }
}

export default function App() {
  const [settings, setSettings] = useState<DashboardSettings>(() => loadSettings())
  const [galleryOpen, setGalleryOpen] = useState(false)
  const [commandOpen, setCommandOpen] = useState(false)
  const { snapshot, client } = useNovaMockClient()

  useEffect(() => {
    saveSettings(settings)
    document.documentElement.dataset.theme = settings.theme
  }, [settings])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(true)
      }
      if (event.key === 'Escape') {
        setGalleryOpen(false)
        setCommandOpen(false)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const installedWidgetIds = useMemo(
    () => new Set(settings.widgets.map(widget => widget.widgetId)),
    [settings.widgets],
  )

  function updateSettings(update: (current: DashboardSettings) => DashboardSettings) {
    setSettings(current => update(current))
  }

  function setMode(mode: ViewMode) {
    updateSettings(current => ({ ...current, mode }))
  }

  function addWidget(widgetId: string) {
    updateSettings(current => ({
      ...current,
      widgets: [...current.widgets, makeWidgetInstance(widgetId)],
    }))
  }

  function removeWidget(instanceId: string) {
    updateSettings(current => ({
      ...current,
      widgets: current.widgets.filter(widget => widget.id !== instanceId),
    }))
  }

  function moveWidget(instanceId: string, direction: -1 | 1) {
    updateSettings(current => {
      const widgets = [...current.widgets]
      const index = widgets.findIndex(widget => widget.id === instanceId)
      const nextIndex = index + direction
      if (index < 0 || nextIndex < 0 || nextIndex >= widgets.length) return current
      const [widget] = widgets.splice(index, 1)
      widgets.splice(nextIndex, 0, widget)
      return { ...current, widgets }
    })
  }

  function resizeWidget(instanceId: string) {
    updateSettings(current => ({
      ...current,
      widgets: current.widgets.map(widget =>
        widget.id === instanceId ? { ...widget, size: nextSize(widget.size) } : widget,
      ),
    }))
  }

  function renderWidget(instance: WidgetInstance, editable = false) {
    const definition = getWidgetDefinition(instance.widgetId)
    if (!definition) return null
    return (
      <div className="widget-frame" key={instance.id}>
        {editable && (
          <div className="widget-toolbar" aria-label={`${definition.title} controls`}>
            <button onClick={() => moveWidget(instance.id, -1)}>Up</button>
            <button onClick={() => moveWidget(instance.id, 1)}>Down</button>
            <button onClick={() => resizeWidget(instance.id)}>Size: {instance.size}</button>
            <button onClick={() => removeWidget(instance.id)}>Remove</button>
          </div>
        )}
        {definition.render({ instance, snapshot, client })}
      </div>
    )
  }

  const visibleWidgets = settings.mode === 'mini'
    ? settings.widgets.slice(0, 3)
    : settings.widgets

  return (
    <main className={`app app-${settings.mode}`} aria-label="NOVA Desktop Companion">
      <div className="ambient" aria-hidden="true" />

      {settings.mode === 'orb' ? (
        <OrbMode status={snapshot.status.agentState} onExpand={() => setMode('mini')} />
      ) : (
        <section className="companion-shell">
          <Header
            settings={settings}
            onModeChange={setMode}
            onGallery={() => setGalleryOpen(true)}
            onCommand={() => setCommandOpen(true)}
            onReset={() => setSettings(resetSettings())}
          />

          {settings.mode === 'mini' && (
            <MiniHero
              taskTitle={snapshot.currentTask?.title ?? 'No active task'}
              status={snapshot.status.agentState}
              onCommand={text => client.sendCommand(text)}
              onExpand={() => setMode('compact')}
            />
          )}

          <div className={`widget-grid grid-${settings.mode}`}>
            {visibleWidgets.map(widget => renderWidget(widget, settings.mode !== 'mini'))}
          </div>
        </section>
      )}

      {galleryOpen && (
        <WidgetGallery
          installedWidgetIds={installedWidgetIds}
          onAdd={addWidget}
          onClose={() => setGalleryOpen(false)}
        />
      )}

      {commandOpen && (
        <CommandPalette
          onClose={() => setCommandOpen(false)}
          onSubmit={text => {
            client.sendCommand(text)
            setCommandOpen(false)
          }}
        />
      )}

      {!settings.onboarded && settings.mode !== 'orb' && (
        <FirstRunPanel
          onFinish={() => setSettings(current => ({ ...current, onboarded: true }))}
          onTheme={theme => setSettings(current => ({ ...current, theme }))}
          onMode={setMode}
        />
      )}
    </main>
  )
}

function OrbMode({ status, onExpand }: { status: string; onExpand: () => void }) {
  return (
    <button className="orb-mode" onClick={onExpand} aria-label="Expand NOVA Mini">
      <span className={`orb-core large state-${status}`} aria-hidden="true" />
      <span>NOVA</span>
      <small>{status}</small>
    </button>
  )
}

function Header({
  settings,
  onModeChange,
  onGallery,
  onCommand,
  onReset,
}: {
  settings: DashboardSettings
  onModeChange: (mode: ViewMode) => void
  onGallery: () => void
  onCommand: () => void
  onReset: () => void
}) {
  return (
    <header className="top-shell">
      <div className="brand-block">
        <div className="brand-mark">N</div>
        <div>
          <strong>NOVA Desktop Companion</strong>
          <span>{settings.pinned ? 'Pinned desktop widget' : 'Floating widget'} - {settings.theme} theme</span>
        </div>
      </div>

      <nav className="mode-switcher" aria-label="Widget size mode">
        {modeLabels.map(mode => (
          <button
            key={mode.id}
            className={settings.mode === mode.id ? 'is-active' : ''}
            onClick={() => onModeChange(mode.id)}
            title={mode.hint}
          >
            {mode.label}
          </button>
        ))}
      </nav>

      <div className="header-actions">
        <button onClick={onCommand}>Ctrl+K</button>
        <button onClick={onGallery}>Widgets</button>
        <button onClick={onReset}>Reset</button>
      </div>
    </header>
  )
}

function MiniHero({
  taskTitle,
  status,
  onCommand,
  onExpand,
}: {
  taskTitle: string
  status: string
  onCommand: (text: string) => void
  onExpand: () => void
}) {
  const [value, setValue] = useState('')
  return (
    <section className="mini-hero" aria-label="NOVA Mini">
      <div className={`orb-core state-${status}`} aria-hidden="true" />
      <div className="mini-copy">
        <p className="eyebrow">Current priority</p>
        <h1>{taskTitle}</h1>
        <span>Status: {status}</span>
      </div>
      <form
        className="mini-command"
        onSubmit={event => {
          event.preventDefault()
          if (!value.trim()) return
          onCommand(value)
          setValue('')
        }}
      >
        <label className="sr-only" htmlFor="mini-command">Ask NOVA</label>
        <input
          id="mini-command"
          value={value}
          onChange={event => setValue(event.target.value)}
          placeholder="Ask NOVA..."
        />
        <button disabled={!value.trim()}>Send</button>
      </form>
      <button className="secondary-button" onClick={onExpand}>Open dashboard</button>
    </section>
  )
}

function WidgetGallery({
  installedWidgetIds,
  onAdd,
  onClose,
}: {
  installedWidgetIds: Set<string>
  onAdd: (widgetId: string) => void
  onClose: () => void
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-panel gallery-panel" role="dialog" aria-modal="true" aria-label="Widget gallery">
        <header className="modal-header">
          <div>
            <p className="eyebrow">Modular system</p>
            <h2>Widget Gallery</h2>
          </div>
          <button onClick={onClose}>Close</button>
        </header>
        <div className="gallery-grid">
          {widgetRegistry.map(widget => (
            <article className="gallery-card" key={widget.id}>
              <p className="eyebrow">{getCategoryLabel(widget.category)}</p>
              <h3>{widget.title}</h3>
              <p>{widget.description}</p>
              <button
                disabled={installedWidgetIds.has(widget.id)}
                onClick={() => onAdd(widget.id)}
              >
                {installedWidgetIds.has(widget.id) ? 'Installed' : 'Add widget'}
              </button>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}

function CommandPalette({ onClose, onSubmit }: { onClose: () => void; onSubmit: (text: string) => void }) {
  const [value, setValue] = useState('')
  return (
    <div className="modal-backdrop" role="presentation">
      <section className="modal-panel command-panel" role="dialog" aria-modal="true" aria-label="NOVA command palette">
        <header className="modal-header">
          <h2>Command NOVA</h2>
          <button onClick={onClose}>Close</button>
        </header>
        <form
          className="palette-form"
          onSubmit={event => {
            event.preventDefault()
            if (!value.trim()) return
            onSubmit(value)
          }}
        >
          <label className="sr-only" htmlFor="palette-input">Command</label>
          <input
            id="palette-input"
            autoFocus
            value={value}
            onChange={event => setValue(event.target.value)}
            placeholder="Remember this, start focus mode, what is due tomorrow..."
          />
          <button disabled={!value.trim()}>Run</button>
        </form>
      </section>
    </div>
  )
}

function FirstRunPanel({
  onFinish,
  onTheme,
  onMode,
}: {
  onFinish: () => void
  onTheme: (theme: DashboardSettings['theme']) => void
  onMode: (mode: ViewMode) => void
}) {
  return (
    <aside className="first-run" aria-label="First run setup">
      <p className="eyebrow">First run</p>
      <h2>Set up NOVA Mini</h2>
      <p>
        This browser build uses a mock NOVA adapter. The Tauri desktop shell and
        real WebSocket bridge are the next integration boundary.
      </p>
      <div className="setup-actions">
        <button onClick={() => onTheme('dark')}>Dark</button>
        <button onClick={() => onTheme('light')}>Light</button>
        <button onClick={() => onMode('mini')}>Start Mini</button>
        <button onClick={() => onMode('compact')}>Start Compact</button>
      </div>
      <button className="primary-button" onClick={onFinish}>Finish setup</button>
    </aside>
  )
}
