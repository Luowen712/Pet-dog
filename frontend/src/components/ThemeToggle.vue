<script setup lang="ts">
import { emitParticleBurst, useTheme } from '@/utils/theme'
import type { ThemeId } from '@/utils/theme'

const { theme, setTheme } = useTheme()

function choose(next: ThemeId, event: MouseEvent): void {
  if (theme.value === next) return
  setTheme(next)
  emitParticleBurst(event.clientX, event.clientY, next === 'phosphor' ? 'oled' : 'accent', 14)
}
</script>

<template>
  <div class="theme-toggle" role="group" aria-label="主题切换">
    <button
      type="button"
      class="theme-opt"
      :class="{ active: theme === 'porcelain' }"
      :aria-pressed="theme === 'porcelain'"
      title="暖釉纸境"
      @click="choose('porcelain', $event)"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 3v2M12 19v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M3 12h2M19 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
      <span>暖釉</span>
    </button>
    <button
      type="button"
      class="theme-opt"
      :class="{ active: theme === 'phosphor' }"
      :aria-pressed="theme === 'phosphor'"
      title="荧光实验"
      @click="choose('phosphor', $event)"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
      </svg>
      <span>荧光</span>
    </button>
  </div>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--hair);
  background: var(--surface-2);
}

.theme-opt {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--dim);
  font-family: var(--sans);
  font-size: 11.5px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition:
    color 0.2s var(--ease-out),
    background-color 0.2s var(--ease-out);
}

.theme-opt svg {
  width: 12.5px;
  height: 12.5px;
  flex-shrink: 0;
}

.theme-opt:hover {
  color: var(--ink);
}

.theme-opt.active {
  background: var(--btn-primary-bg);
  color: var(--btn-primary-ink);
}

@media (max-width: 640px) {
  .theme-opt span {
    display: none;
  }
  .theme-opt {
    padding: 0 8px;
  }
}
</style>
