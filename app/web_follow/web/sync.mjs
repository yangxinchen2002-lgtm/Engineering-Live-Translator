// Pure media-clock decisions shared by the page and dependency-free Node tests.
export function activeCue(cues, time) {
  return [...cues].reverse().find(c => c.start <= time && time < c.end) || null;
}
export function enoughBuffer(state, time, threshold = 3) {
  if (!state || !['ready', 'preparing'].includes(state.status)) return false;
  if (state.duration != null && time >= state.duration - .05) return true;
  return state.prepared_until >= Math.min(time + threshold, state.duration ?? Infinity) - .05;
}
