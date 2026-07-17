import { useState, type ReactNode } from 'react'
import type {
  Assignment,
  NovaClient,
  NovaSnapshot,
  NovaTask,
  TaskStatus,
  WidgetCategory,
  WidgetDefinition,
  WidgetInstance,
  WidgetSize,
} from './types'

export interface WidgetProps {
  instance: WidgetInstance
  snapshot: NovaSnapshot
  client: NovaClient
}

type WidgetRenderer = (props: WidgetProps) => ReactNode

interface RegistryEntry extends WidgetDefinition {
  render: WidgetRenderer
}

const categoryLabel: Record<WidgetCategory, string> = {
  essential: 'Essential',
  school: 'School',
  memory: 'Memory',
  projects: 'Projects',
  nova: 'NOVA',
  system: 'System',
  lifestyle: 'Lifestyle',
}

const taskStatusLabel: Record<TaskStatus, string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  done: 'Done',
  blocked: 'Blocked',
}

function WidgetShell({ title, meta, size, children }: { title: string; meta: string; size: WidgetSize; children: ReactNode }) {
  return (
    <section className={`widget widget-${size}`} aria-label={title}>
      <header className="widget-header">
        <div>
          <p className="eyebrow">{meta}</p>
          <h2>{title}</h2>
        </div>
      </header>
      <div className="widget-body">{children}</div>
    </section>
  )
}

function StatusPill({ label, tone = 'info' }: { label: string; tone?: 'info' | 'success' | 'warning' | 'danger' }) {
  return <span className={`status-pill tone-${tone}`}>{label}</span>
}

function TaskRow({ task, client }: { task: NovaTask; client: NovaClient }) {
  const done = task.status === 'done'
  return (
    <article className="task-row">
      <button
        className={`check-button ${done ? 'is-done' : ''}`}
        onClick={() => done ? client.reopenTask(task.id) : client.completeTask(task.id)}
        aria-label={done ? `Reopen ${task.title}` : `Mark ${task.title} complete`}
      >
        {done ? 'Done' : 'Mark'}
      </button>
      <div className="task-main">
        <strong>{task.title}</strong>
        <span>{task.source} - {task.dueLabel ?? 'No due date'} - {taskStatusLabel[task.status]}</span>
      </div>
      <StatusPill label={task.priority} tone={task.priority === 'high' ? 'danger' : task.priority === 'medium' ? 'warning' : 'info'} />
    </article>
  )
}

function AssignmentRow({ assignment }: { assignment: Assignment }) {
  return (
    <article className="assignment-row">
      <div>
        <strong>{assignment.title}</strong>
        <span>{assignment.course} - {assignment.provider}</span>
      </div>
      <div className="assignment-meta">
        <StatusPill label={assignment.dueLabel} tone={assignment.priority === 'high' ? 'danger' : 'warning'} />
        <span>{taskStatusLabel[assignment.status]}</span>
      </div>
    </article>
  )
}

function NovaStatusWidget({ snapshot, instance }: WidgetProps) {
  const status = snapshot.status
  return (
    <WidgetShell title="NOVA Mini" meta="Agent status" size={instance.size}>
      <div className="nova-status-grid">
        <div className={`orb-core state-${status.agentState}`} aria-hidden="true" />
        <div>
          <p className="large-label">{status.agentState}</p>
          <p className="muted">{status.activeModel} - {status.connection}</p>
          <div className="pill-row">
            <StatusPill label={status.micEnabled ? 'Mic on' : 'Mic off'} tone={status.micEnabled ? 'success' : 'warning'} />
            <StatusPill label={status.privacyMode ? 'Privacy on' : 'Privacy off'} tone="info" />
          </div>
        </div>
      </div>
    </WidgetShell>
  )
}

function QuickInputWidget({ client, instance }: WidgetProps) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)

  function submit() {
    if (!value.trim() || busy) return
    setBusy(true)
    client.sendCommand(value)
    window.setTimeout(() => {
      setBusy(false)
      setValue('')
    }, 450)
  }

  return (
    <WidgetShell title="Ask NOVA" meta="Command box" size={instance.size}>
      <label className="sr-only" htmlFor="nova-command">Ask NOVA</label>
      <div className="command-row">
        <input
          id="nova-command"
          value={value}
          onChange={event => setValue(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter') submit()
          }}
          placeholder="Open VS Code, remember this, what is due tomorrow..."
        />
        <button className="primary-button" onClick={submit} disabled={busy || !value.trim()}>
          {busy ? 'Sending' : 'Ask'}
        </button>
      </div>
    </WidgetShell>
  )
}

function CurrentPriorityWidget({ snapshot, client, instance }: WidgetProps) {
  const task = snapshot.currentTask
  return (
    <WidgetShell title="Current Priority" meta="Mission control" size={instance.size}>
      {task ? (
        <div className="priority-card">
          <div>
            <p className="large-label">{task.title}</p>
            <p className="muted">{task.estimateMinutes ?? 0} min estimate - {taskStatusLabel[task.status]}</p>
          </div>
          <div className="action-row">
            <button onClick={() => client.completeTask(task.id)}>Complete</button>
            <button onClick={() => client.postponeTask(task.id)}>Postpone</button>
          </div>
        </div>
      ) : (
        <p className="muted">No active task.</p>
      )}
    </WidgetShell>
  )
}

function TaskListWidget({ snapshot, client, instance }: WidgetProps) {
  return (
    <WidgetShell title="Tasks" meta="Done / not done" size={instance.size}>
      <div className="stack">
        {snapshot.tasks.map(task => <TaskRow key={task.id} task={task} client={client} />)}
      </div>
    </WidgetShell>
  )
}

function SchoolAssignmentsWidget({ snapshot, instance }: WidgetProps) {
  return (
    <WidgetShell title="School" meta="Canvas / Blackboard / D2L" size={instance.size}>
      <div className="summary-row">
        <StatusPill label={`${snapshot.assignments.filter(a => a.priority === 'high').length} high`} tone="danger" />
        <StatusPill label={`${snapshot.assignments.filter(a => a.status !== 'done').length} open`} tone="warning" />
        <StatusPill label="Mock adapters" tone="info" />
      </div>
      <div className="stack">
        {snapshot.assignments.map(assignment => <AssignmentRow key={assignment.id} assignment={assignment} />)}
      </div>
    </WidgetShell>
  )
}

function ObsidianMemoryWidget({ snapshot, client, instance }: WidgetProps) {
  const [note, setNote] = useState('')
  return (
    <WidgetShell title="Obsidian Memory" meta="Vault state" size={instance.size}>
      <div className="memory-stats">
        <strong>{snapshot.memory.indexedNotes}</strong>
        <span>indexed notes</span>
        <strong>{snapshot.memory.updatedToday}</strong>
        <span>updated today</span>
      </div>
      <div className="stack compact">
        {snapshot.memory.recent.map(item => (
          <article className="memory-row" key={item.id}>
            <strong>{item.title}</strong>
            <span>{item.path} - {item.updated}</span>
          </article>
        ))}
      </div>
      <div className="command-row">
        <input value={note} onChange={event => setNote(event.target.value)} placeholder="Quick memory note" />
        <button onClick={() => { client.addQuickNote(note); setNote('') }} disabled={!note.trim()}>Stage</button>
      </div>
    </WidgetShell>
  )
}

function ActivityFeedWidget({ snapshot, instance }: WidgetProps) {
  return (
    <WidgetShell title="Operational Activity" meta="Observable events" size={instance.size}>
      <div className="timeline-list">
        {snapshot.events.map(item => (
          <article key={item.id} className={`event-row level-${item.level}`}>
            <time>{item.at}</time>
            <div>
              <strong>{item.label}</strong>
              <span>{item.detail}</span>
            </div>
          </article>
        ))}
      </div>
    </WidgetShell>
  )
}

function ModelHealthWidget({ snapshot, instance }: WidgetProps) {
  return (
    <WidgetShell title="Models" meta="Routing health" size={instance.size}>
      <div className="stack compact">
        {snapshot.models.map(model => (
          <article className="model-row" key={model.id}>
            <div>
              <strong>{model.label}</strong>
              <span>{model.currentTask}</span>
            </div>
            <StatusPill label={`${model.latencyMs} ms`} tone={model.online ? 'success' : 'danger'} />
          </article>
        ))}
      </div>
    </WidgetShell>
  )
}

function SystemMonitorWidget({ snapshot, instance }: WidgetProps) {
  return (
    <WidgetShell title="System" meta="Local health" size={instance.size}>
      <div className="metric-grid">
        <div><strong>{snapshot.system.cpu}%</strong><span>CPU</span></div>
        <div><strong>{snapshot.system.ram}%</strong><span>RAM</span></div>
        <div><strong>{snapshot.system.network}</strong><span>Network</span></div>
        <div><strong>{snapshot.system.battery}</strong><span>Battery</span></div>
      </div>
    </WidgetShell>
  )
}

function ProjectsWidget({ instance }: WidgetProps) {
  return (
    <WidgetShell title="Projects" meta="Active work" size={instance.size}>
      <div className="stack compact">
        {[
          ['NOVA', 84],
          ['Cooking App', 62],
          ['Hackathon', 39],
        ].map(([name, progress]) => (
          <article className="project-row" key={name}>
            <div>
              <strong>{name}</strong>
              <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
            </div>
            <span>{progress}%</span>
          </article>
        ))}
      </div>
    </WidgetShell>
  )
}

function SuggestionsWidget({ instance }: WidgetProps) {
  return (
    <WidgetShell title="Suggestions" meta="Habit engine" size={instance.size}>
      <div className="suggestion-list">
        <button>Continue coding NOVA dashboard</button>
        <button>Review upcoming school tasks</button>
        <button>Save a short decision log</button>
      </div>
    </WidgetShell>
  )
}

export const widgetRegistry: RegistryEntry[] = [
  {
    id: 'nova-status',
    title: 'NOVA Status',
    description: 'Orb, model, mic, privacy, and connection state.',
    category: 'essential',
    defaultSize: 'medium',
    render: NovaStatusWidget,
  },
  {
    id: 'quick-input',
    title: 'Quick Input',
    description: 'Submit a command through the NOVA service boundary.',
    category: 'essential',
    defaultSize: 'medium',
    render: QuickInputWidget,
  },
  {
    id: 'current-priority',
    title: 'Current Priority',
    description: 'The one task NOVA thinks matters most now.',
    category: 'essential',
    defaultSize: 'medium',
    render: CurrentPriorityWidget,
  },
  {
    id: 'task-list',
    title: 'Task List',
    description: 'Done, in progress, blocked, and not-started work.',
    category: 'essential',
    defaultSize: 'large',
    render: TaskListWidget,
  },
  {
    id: 'school-assignments',
    title: 'School Assignments',
    description: 'Normalized Canvas, Blackboard, and D2L assignment cards.',
    category: 'school',
    defaultSize: 'large',
    render: SchoolAssignmentsWidget,
  },
  {
    id: 'obsidian-memory',
    title: 'Obsidian Memory',
    description: 'Vault status, recent notes, quick note staging.',
    category: 'memory',
    defaultSize: 'medium',
    render: ObsidianMemoryWidget,
  },
  {
    id: 'activity-feed',
    title: 'Activity Feed',
    description: 'Observable events without private chain-of-thought.',
    category: 'nova',
    defaultSize: 'medium',
    render: ActivityFeedWidget,
  },
  {
    id: 'model-health',
    title: 'Model Health',
    description: 'Connected model status and mock latency.',
    category: 'nova',
    defaultSize: 'medium',
    render: ModelHealthWidget,
  },
  {
    id: 'system-monitor',
    title: 'System Monitor',
    description: 'Local CPU, RAM, battery, and network summary.',
    category: 'system',
    defaultSize: 'small',
    render: SystemMonitorWidget,
  },
  {
    id: 'projects',
    title: 'Projects',
    description: 'NOVA, cooking app, and hackathon progress.',
    category: 'projects',
    defaultSize: 'medium',
    render: ProjectsWidget,
  },
  {
    id: 'suggestions',
    title: 'Suggestions',
    description: 'Low-pressure next actions based on current context.',
    category: 'lifestyle',
    defaultSize: 'small',
    render: SuggestionsWidget,
  },
]

export function getWidgetDefinition(widgetId: string): RegistryEntry | undefined {
  return widgetRegistry.find(widget => widget.id === widgetId)
}

export function getCategoryLabel(category: WidgetCategory): string {
  return categoryLabel[category]
}
