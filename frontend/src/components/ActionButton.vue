<script setup lang="ts">
import { computed } from 'vue'
import type { ActionDef } from '@/constants/actions'
import { actionHex } from '@/constants/actions'
import type { ButtonState } from '@/stores/pet'
import { emitParticleBurst } from '@/utils/theme'

const props = defineProps<{ action: ActionDef; state: ButtonState; disabled?: boolean }>()
const emit = defineEmits<{ (event: 'click'): void }>()

const title = computed(() => {
  if (props.disabled) return `${props.action.name} · 未启用`
  const stateText: Record<ButtonState, string> = {
    idle: props.action.hint,
    pending: '已提交，等待设备受理',
    accepted: '设备已受理，执行中',
    ok: '执行完成',
    fail: '动作未完成',
    unknown: '结果不明',
  }
  return `${props.action.name} (${actionHex(props.action.code)}) · ${stateText[props.state]}`
})

function handleClick(event: MouseEvent): void {
  if (props.disabled) return
  if (event.clientX > 0) emitParticleBurst(event.clientX, event.clientY, 'accent', 14)
  emit('click')
}
</script>

<template>
  <button
    type="button"
    class="action-btn"
    :class="[state, { disabled }]"
    :title="title"
    :disabled="disabled"
    @click="handleClick"
  >
    <span class="row">
      <span class="code mono">{{ actionHex(action.code) }}</span>
      <span class="state-dot" />
    </span>
    <span class="label">{{ action.name }}</span>
  </button>
</template>

<style scoped>
.action-btn {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  padding: 11px 12px 12px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  cursor: pointer;
  text-align: left;
  overflow: hidden;
  transition:
    border-color 0.2s var(--ease-out),
    background-color 0.2s var(--ease-out),
    transform 0.2s var(--ease-out);
}

.action-btn::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: var(--grad-line);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.22s var(--ease-out);
}

.action-btn:hover:not(.disabled) {
  border-color: var(--hair-strong);
  background: var(--surface-3);
  transform: translateY(-2px);
}

.action-btn:hover:not(.disabled)::after {
  transform: scaleX(1);
}

.action-btn:active:not(.disabled) {
  transform: translateY(0);
}

.action-btn.disabled {
  cursor: not-allowed;
  background: transparent;
  border-color: var(--hair-soft);
  opacity: 0.42;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.code {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: var(--dim);
}

.label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
}

.state-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--hair-strong);
}

.action-btn.pending,
.action-btn.accepted {
  background: var(--warn-soft);
  border-color: var(--warn-border);
}

.action-btn.pending .state-dot,
.action-btn.accepted .state-dot {
  background: var(--warn);
  animation: pulse 0.95s ease-in-out infinite;
}

.action-btn.ok {
  background: var(--ok-soft);
  border-color: var(--ok-border);
}

.action-btn.ok .state-dot {
  background: var(--ok);
}

.action-btn.fail,
.action-btn.unknown {
  background: var(--warn-soft);
  border-color: var(--warn-border);
}

.action-btn.fail .state-dot,
.action-btn.unknown .state-dot {
  background: var(--warn);
}

@keyframes pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(255, 179, 71, 0.45);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(255, 179, 71, 0);
  }
}
</style>
