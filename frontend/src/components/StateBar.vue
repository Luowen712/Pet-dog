<script setup lang="ts">
import { computed } from 'vue'
import { actionName } from '@/constants/actions'
import { faceName } from '@/constants/faces'
import { formatTrack } from '@/utils/format'
import { usePetStore } from '@/stores/pet'

const pet = usePetStore()

const batteryColor = computed(() => {
  if (pet.battery > 50) return '#2f6b4f'
  if (pet.battery > 20) return '#9a6a1c'
  return '#a53a33'
})

const batteryPercent = computed(() => Math.max(0, Math.min(100, pet.battery)))
</script>

<template>
  <div class="state-bar">
    <div class="stat">
      <span class="stat-label mono">Battery</span>
      <div class="battery">
        <span class="battery-num mono">{{ pet.battery }}<i>%</i></span>
        <el-progress
          class="battery-bar"
          :percentage="batteryPercent"
          :stroke-width="2"
          :show-text="false"
          :color="batteryColor"
        />
      </div>
    </div>

    <div class="stat">
      <span class="stat-label mono">Voltage</span>
      <span class="stat-value mono">{{ pet.voltage.toFixed(2) }} <i>V</i></span>
    </div>

    <div class="stat">
      <span class="stat-label mono">Action</span>
      <span class="stat-value">{{ actionName(pet.action) }}</span>
    </div>

    <div class="stat">
      <span class="stat-label mono">Face</span>
      <span class="stat-value">{{ faceName(pet.face) }}</span>
    </div>

    <div class="stat">
      <span class="stat-label mono">Music</span>
      <span class="stat-value">
        {{ pet.musicLabel }}
        <i class="mono track">{{ formatTrack(pet.track) }}</i>
      </span>
    </div>

    <div class="link">
      <span class="dot" :class="{ online: pet.connected }" />
      <span class="mono">{{ pet.connected ? 'LINK OK' : 'LINK LOST' }}</span>
    </div>
  </div>
</template>

<style scoped>
.state-bar {
  display: grid;
  grid-template-columns: 1.1fr 0.8fr 1fr 0.7fr 1.1fr auto;
  align-items: stretch;
  background: var(--panel);
  border: 1px solid var(--hair);
  border-radius: var(--radius);
  overflow: hidden;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
  padding: 13px 16px 14px;
  border-left: 1px solid var(--hair-soft);
}

.stat:first-child {
  border-left: 0;
}

.stat-label {
  font-size: 8.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.stat-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-value i {
  font-style: normal;
  font-size: 10px;
  color: var(--faint);
  margin-left: 2px;
}

.track {
  margin-left: 4px;
  color: var(--dim);
}

.battery {
  display: flex;
  align-items: center;
  gap: 10px;
}

.battery-num {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

.battery-num i {
  font-style: normal;
  font-size: 9px;
  color: var(--faint);
}

.battery-bar {
  flex: 1;
  min-width: 34px;
}

.link {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 16px;
  border-left: 1px solid var(--hair-soft);
  font-size: 8.5px;
  letter-spacing: 0.12em;
  color: var(--faint);
  white-space: nowrap;
}

@media (max-width: 1180px) {
  .state-bar {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .stat:nth-child(4) {
    border-left: 0;
  }

  .stat:nth-child(n + 4) {
    border-top: 1px solid var(--hair-soft);
  }

  .link {
    border-top: 1px solid var(--hair-soft);
    padding: 12px 16px;
  }
}

@media (max-width: 640px) {
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
  }
}
</style>
