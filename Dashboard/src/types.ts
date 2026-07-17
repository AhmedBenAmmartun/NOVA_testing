export type ViewMode = 'orb' | 'mini' | 'compact' | 'full'
export type ThemeMode = 'dark' | 'light' | 'system'
export type WidgetCategory =
  | 'essential'
  | 'school'
  | 'memory'
  | 'projects'
  | 'nova'
  | 'system'
  | 'lifestyle'
export type WidgetSize = 'small' | 'medium' | 'large'
export type TaskStatus = 'not_started' | 'in_progress' | 'done' | 'blocked'
export type Sensitivity = 'safe' | 'reversible' | 'sensitive' | 'destructive'

export interface WidgetDefinition {
  id: string
  title: string
  description: string
  category: WidgetCategory
  defaultSize: WidgetSize
}

export interface WidgetInstance {
  id: string
  widgetId: string
  size: WidgetSize
}

export interface DashboardSettings {
  version: number
  mode: ViewMode
  theme: ThemeMode
  pinned: boolean
  activePage: string
  widgets: WidgetInstance[]
  onboarded: boolean
}

export interface NovaStatus {
  connection: 'connected' | 'connecting' | 'offline'
  agentState: 'ready' | 'listening' | 'understanding' | 'acting' | 'speaking' | 'error'
  activeModel: string
  micEnabled: boolean
  cameraEnabled: boolean
  screenCaptureActive: boolean
  privacyMode: boolean
}

export interface NovaTask {
  id: string
  title: string
  source: 'nova' | 'canvas' | 'blackboard' | 'd2l' | 'obsidian' | 'manual'
  status: TaskStatus
  priority: 'high' | 'medium' | 'low'
  dueLabel?: string
  estimateMinutes?: number
  sensitivity: Sensitivity
  subtasks?: Array<{ id: string; title: string; done: boolean }>
}

export interface Assignment {
  id: string
  provider: 'Canvas' | 'Blackboard' | 'D2L Brightspace'
  course: string
  title: string
  dueLabel: string
  status: TaskStatus
  priority: 'high' | 'medium' | 'low'
}

export interface MemorySummary {
  vaultConnected: boolean
  indexedNotes: number
  updatedToday: number
  indexHealth: 'healthy' | 'stale' | 'offline'
  recent: Array<{ id: string; title: string; path: string; updated: string }>
  tags: string[]
}

export interface NovaEvent {
  id: string
  at: string
  kind: 'voice' | 'tool' | 'memory' | 'model' | 'task' | 'system'
  label: string
  detail: string
  level: 'info' | 'success' | 'warning' | 'error'
}

export interface NovaSnapshot {
  status: NovaStatus
  currentTask: NovaTask | null
  tasks: NovaTask[]
  assignments: Assignment[]
  memory: MemorySummary
  events: NovaEvent[]
  system: {
    cpu: number
    ram: number
    network: 'good' | 'slow' | 'offline'
    battery: string
  }
  models: Array<{
    id: string
    label: string
    online: boolean
    latencyMs: number
    currentTask: string
  }>
}

export interface NovaClient {
  completeTask(taskId: string): void
  reopenTask(taskId: string): void
  postponeTask(taskId: string): void
  addQuickNote(text: string): void
  sendCommand(text: string): void
}
