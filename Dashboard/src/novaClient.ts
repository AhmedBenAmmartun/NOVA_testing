import { useCallback, useEffect, useMemo, useState } from 'react'
import type { NovaClient, NovaEvent, NovaSnapshot, NovaTask, TaskStatus } from './types'

const initialTasks: NovaTask[] = [
  {
    id: 'task-dashboard',
    title: 'Build modular desktop widget',
    source: 'nova',
    status: 'in_progress',
    priority: 'high',
    dueLabel: 'Today',
    estimateMinutes: 90,
    sensitivity: 'safe',
    subtasks: [
      { id: 'audit', title: 'Audit dashboard scaffold', done: true },
      { id: 'mini', title: 'Implement Mini mode', done: true },
      { id: 'widgets', title: 'Add widget registry', done: true },
      { id: 'bridge', title: 'Connect live NOVA event bridge', done: false },
    ],
  },
  {
    id: 'task-study',
    title: 'Verify quiz mode after quota reset',
    source: 'manual',
    status: 'not_started',
    priority: 'medium',
    dueLabel: 'Later',
    estimateMinutes: 30,
    sensitivity: 'safe',
  },
  {
    id: 'task-memory',
    title: 'Review new Obsidian memory notes',
    source: 'obsidian',
    status: 'not_started',
    priority: 'low',
    dueLabel: 'This week',
    estimateMinutes: 20,
    sensitivity: 'safe',
  },
]

function event(kind: NovaEvent['kind'], label: string, detail: string, level: NovaEvent['level'] = 'info'): NovaEvent {
  return {
    id: crypto.randomUUID(),
    at: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    kind,
    label,
    detail,
    level,
  }
}

function updateTask(tasks: NovaTask[], taskId: string, status: TaskStatus): NovaTask[] {
  return tasks.map(task => task.id === taskId ? { ...task, status } : task)
}

export function useNovaMockClient(): { snapshot: NovaSnapshot; client: NovaClient } {
  const [tasks, setTasks] = useState<NovaTask[]>(initialTasks)
  const [tick, setTick] = useState(0)
  const [events, setEvents] = useState<NovaEvent[]>([
    event('system', 'Dashboard shell restored', 'Loaded saved widget layout.', 'success'),
    event('memory', 'Obsidian connected', 'NOVA vault index available.', 'success'),
    event('tool', 'Driver check', 'Last local tool smoke test passed 31/31.', 'success'),
  ])
  const [agentState, setAgentState] = useState<NovaSnapshot['status']['agentState']>('ready')

  useEffect(() => {
    const states: NovaSnapshot['status']['agentState'][] = ['ready', 'listening', 'understanding', 'acting', 'speaking']
    const labels = [
      event('voice', 'Listening window idle', 'Microphone ready, no active utterance.'),
      event('memory', 'Vault mirror ready', 'Conversation transcripts mirror to NOVA/Conversations.'),
      event('tool', 'Safe action boundary', 'Sensitive actions require confirmation.'),
      event('model', 'Model health sampled', 'Gemini service health checked by mock adapter.'),
    ]

    const id = window.setInterval(() => {
      setTick(value => value + 1)
      setAgentState(states[Math.floor(Math.random() * states.length)])
      setEvents(previous => [labels[Math.floor(Math.random() * labels.length)], ...previous].slice(0, 12))
    }, 8000)

    return () => window.clearInterval(id)
  }, [])

  const client = useMemo<NovaClient>(() => ({
    completeTask(taskId: string) {
      setTasks(current => updateTask(current, taskId, 'done'))
      setEvents(previous => [event('task', 'Task completed', taskId, 'success'), ...previous].slice(0, 12))
    },
    reopenTask(taskId: string) {
      setTasks(current => updateTask(current, taskId, 'in_progress'))
      setEvents(previous => [event('task', 'Task reopened', taskId, 'info'), ...previous].slice(0, 12))
    },
    postponeTask(taskId: string) {
      setTasks(current => updateTask(current, taskId, 'not_started'))
      setEvents(previous => [event('task', 'Task postponed', taskId, 'warning'), ...previous].slice(0, 12))
    },
    addQuickNote(text: string) {
      const trimmed = text.trim()
      if (!trimmed) return
      setEvents(previous => [event('memory', 'Quick note staged', trimmed.slice(0, 120), 'success'), ...previous].slice(0, 12))
    },
    sendCommand(text: string) {
      const trimmed = text.trim()
      if (!trimmed) return
      setAgentState('acting')
      setEvents(previous => [event('tool', 'Command submitted', trimmed.slice(0, 120), 'info'), ...previous].slice(0, 12))
    },
  }), [])

  const currentTask = tasks.find(task => task.status === 'in_progress') ?? tasks[0] ?? null

  const snapshot: NovaSnapshot = useMemo(() => ({
    status: {
      connection: tick % 11 === 0 ? 'connecting' : 'connected',
      agentState,
      activeModel: 'Gemini Live',
      micEnabled: true,
      cameraEnabled: false,
      screenCaptureActive: false,
      privacyMode: true,
    },
    currentTask,
    tasks,
    assignments: [
      {
        id: 'school-os',
        provider: 'Canvas',
        course: 'Operating Systems',
        title: 'Scheduler lab reflection',
        dueLabel: 'Tomorrow',
        status: 'not_started',
        priority: 'high',
      },
      {
        id: 'school-se',
        provider: 'Blackboard',
        course: 'Software Engineering',
        title: 'Sprint report',
        dueLabel: '2 days',
        status: 'in_progress',
        priority: 'medium',
      },
      {
        id: 'school-ml',
        provider: 'D2L Brightspace',
        course: 'Machine Learning',
        title: 'Quiz review',
        dueLabel: 'Friday',
        status: 'not_started',
        priority: 'medium',
      },
    ],
    memory: {
      vaultConnected: true,
      indexedNotes: 428,
      updatedToday: 21,
      indexHealth: 'healthy',
      recent: [
        { id: 'm1', title: 'NOVA conversations', path: 'NOVA/Conversations', updated: '3 min ago' },
        { id: 'm2', title: 'Dashboard ideas', path: 'Projects/NOVA', updated: '18 min ago' },
        { id: 'm3', title: 'Cooking app references', path: 'Projects/Cooking', updated: 'Today' },
      ],
      tags: ['nova', 'coding', 'school', 'cooking', 'hackathon'],
    },
    events,
    system: {
      cpu: 34 + (tick % 20),
      ram: 58 + (tick % 12),
      network: tick % 17 === 0 ? 'slow' : 'good',
      battery: 'Charging',
    },
    models: [
      { id: 'gemini', label: 'Gemini Live', online: true, latencyMs: 180, currentTask: 'voice' },
      { id: 'openai', label: 'GPT-5.6', online: true, latencyMs: 420, currentTask: 'opt-in reasoning' },
      { id: 'groq', label: 'Groq', online: true, latencyMs: 95, currentTask: 'idle' },
      { id: 'ollama', label: 'Ollama', online: true, latencyMs: 32, currentTask: 'local fallback' },
    ],
  }), [agentState, currentTask, events, tasks, tick])

  useEffect(() => {
    const onOnline = () => setEvents(previous => [event('system', 'Network online', 'Mock adapter reconnected.', 'success'), ...previous].slice(0, 12))
    const onOffline = () => setEvents(previous => [event('system', 'Network offline', 'Using cached widget data.', 'warning'), ...previous].slice(0, 12))
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  return { snapshot, client }
}

export function useStableCallback<T extends (...args: never[]) => unknown>(callback: T): T {
  return useCallback(callback, [callback]) as T
}
