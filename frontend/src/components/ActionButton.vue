<script setup lang="ts">
import { computed } from 'vue'
import type { ActionDef } from '@/constants/actions'
import { actionHex } from '@/constants/actions'
import type { ButtonState } from '@/stores/pet'

const props = defineProps<{ action: ActionDef; state: ButtonState }>()
defineEmits<{ (event: 'click'): void }>()

const title = computed(() => `${props.action.name} · 动作码 ${actionHex(props.action.code)} · ${props.action.hint}`)
</script>

<template>
  <button
    type="button"
    class="action-btn"
    :class="state"
    :title="title"
    @click="$emit('click')"
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
  gap: 9px;
  width: 100%;
  padding: 9px 11px 10px;
  border: 1px solid var(--hair);
  border-radius: var(--radius);
  background: var(--panel);
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}

.action-btn::after {
  content: '';
  position: absolute;
  left: -1px;
  right: -1px;
  bottom: -1px;
  height: 1px;
  background: var(--grad-line);
  opacity: 0;
  transition: opacity 0.18s ease;
}

.action-btn:hover {
  border-color: rgba(20, 20, 20, 0.38);
}

.action-btn:hover::after {
  opacity: 1;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.code {
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--faint);
}

.label {
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.01em;
  color: var(--ink);
}

.state-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: rgba(20, 20, 20, 0.18);
}

.action-btn.pending {
  background: #fbf2e3;
  border-color: rgba(154, 106, 28, 0.42);
}

.action-btn.pending .state-dot {
  background: var(--warn);
  animation: pulse 1s ease-in-out infinite;
}

.action-btn.ok {
  background: #eef3ee;
  border-color: rgba(47, 107, 79, 0.38);
}

.action-btn.ok .state-dot {
  background: var(--ok);
}

.action-btn.fail {
  background: #f8ecea;
  border-color: rgba(165, 58, 51, 0.38);
}

.action-btn.fail .state-dot {
  background: var(--danger);
}

@keyframes pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(154, 106, 28, 0.4);
  }
  50% {
    box-shadow: 0 0 0 4px rgba(154, 106, 28, 0);
  }
}
</style>
