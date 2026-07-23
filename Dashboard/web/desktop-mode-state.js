export function createDesktopState() {
  return {
    mode: 'desktop',
    clickThrough: false,
    editing: false,
    resumeClickThrough: false,
  }
}

export function reduceDesktopState(state, event) {
  switch (event.type) {
    case 'enter-desktop':
    case 'enter-dashboard':
    case 'toggle-mode':
      return {
        ...state,
        mode: 'desktop',
        clickThrough: false,
        editing: false,
        resumeClickThrough: false,
      }
    case 'toggle-click-through':
      if (state.editing) return state
      return { ...state, clickThrough: !state.clickThrough }
    case 'set-editing': {
      const editing = Boolean(event.editing)
      if (editing) {
        return {
          ...state,
          mode: 'desktop',
          editing: true,
          resumeClickThrough: state.clickThrough,
          clickThrough: false,
        }
      }
      if (!state.editing) return state
      return {
        ...state,
        mode: 'desktop',
        editing: false,
        clickThrough: state.resumeClickThrough,
        resumeClickThrough: false,
      }
    }
    default:
      return state
  }
}
