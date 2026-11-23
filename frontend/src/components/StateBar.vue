<script setup lang="ts">
import { computed } from 'vue'
import { actionName } from '@/constants/actions'
import { faceName } from '@/constants/faces'
import { describeDeviceStatus } from '@/utils/format'
import { usePetStore } from '@/stores/pet'

const pet = usePetStore()

const batteryColor = computed(() => {
  if (pet.battery === null) return 'var(--faint)'
  if (pet.battery > 50) return 'var(--ok)'
  if (pet.battery > 20) return 'var(--warn)'
  return 'var(--danger)'
})

const batteryPercent = computed(() =>
  pet.battery === null ? 0 : Math.max(0, Math.min(100, pet.battery)),
)

const statusView = computed(() =>
  describeDeviceStatus({
    online: pet.online,
    controlState: pet.controlState,
  }),
)
</script>

<template>
  <div class="state-bar card">
    <div class="stat">
      <span class="stat-label">电量</span>
      <div class="battery">
        <span class="battery-num mono">{{ pet.battery ?? '--' }}<i>%</i></span>
        <div class="battery-track">
          <div
            class="battery-fill"
            :style="{ width: `${batteryPercent}%`, backgroundColor: batteryColor }"
          />
        </div>
      </div>
    </div>

    <div class="stat">
      <span class="stat-label">电压</span>
      <span class="stat-value mono">
        {{ pet.voltage === null ? '--' : pet.voltage.toFixed(2) }}<i>V</i>
      </span>
    </div>

    <div class="stat">
      <span class="stat-label">当前动作</span>
      <span class="stat-value">{{ pet.action === null ? '—' : actionName(pet.action) }}</span>
    </div>

    <div class="stat">
      <span class="stat-label">当前表情</span>
      <span class="stat-value">{{ pet.face === null ? '—' : faceName(pet.face) }}</span>
    </div>

    <div class="link">
      <span class="status" :class="statusView.tone">{{ statusView.label }}</span>
    </div>
  </div>
</template>

<style scoped>
.state-bar {
  display: grid;
  grid-template-columns: 1.2fr 0.85fr 1fr 0.85fr auto;
  align-items: stretch;
}

.stat {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  min-width: 0;
  padding: 14px 18px;
  border-left: 1px solid var(--hair-soft);
}

.stat:first-child {
  border-left: 0;
}

.stat-label {
  font-size: 11px;
  color: var(--dim);
}

.stat-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-value i,
.battery-num i {
  font-style: normal;
  font-size: 10px;
  color: var(--faint);
  margin-left: 2px;
}

.battery {
  display: flex;
  align-items: center;
  gap: 10px;
}

.battery-num {
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
}

.battery-track {
  flex: 1;
  min-width: 40px;
  height: 5px;
  border-radius: var(--radius-pill);
  background: var(--hair);
  overflow: hidden;
}

.battery-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.38s var(--ease-out);
}

.link {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 12px 18px;
  border-left: 1px solid var(--hair-soft);
}

@media (max-width: 1120px) {
  .state-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .stat:nth-child(odd) {
    border-left: 0;
  }

  .stat:nth-child(n + 3) {
    border-top: 1px solid var(--hair-soft);
  }

  .link {
    grid-column: 1 / -1;
    border-left: 0;
    border-top: 1px solid var(--hair-soft);
    justify-content: flex-start;
  }
}
</style>
