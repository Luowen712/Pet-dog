<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import EmptyState from '@/components/EmptyState.vue'
import type { Device } from '@/types'
import { formatDateTime, formatRelative } from '@/utils/format'
import { useDeviceStore } from '@/stores/device'

const router = useRouter()
const deviceStore = useDeviceStore()

onMounted(() => {
  if (!deviceStore.loaded) void deviceStore.load()
})

const summary = computed(() => `${deviceStore.devices.length} 台设备，${deviceStore.onlineCount} 台在线`)

function enter(device: Device): void {
  deviceStore.select(device.id)
  void router.push('/console')
}

function refresh(): void {
  void deviceStore.load()
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <div class="page-kicker">02 / Devices</div>
        <h2 class="page-title">我的设备</h2>
        <p class="page-sub">{{ summary }} · 选一台进入控制台</p>
      </div>
      <el-button class="ghost" :icon="Refresh" :loading="deviceStore.loading" @click="refresh">
        刷新
      </el-button>
    </div>

    <el-skeleton v-if="deviceStore.loading && !deviceStore.loaded" :rows="4" animated />

    <div v-else-if="deviceStore.devices.length === 0" class="card">
      <EmptyState title="还没有设备，先让后端注册一台桌宠" hint="No devices" />
    </div>

    <div v-else class="grid">
      <article
        v-for="(device, index) in deviceStore.devices"
        :key="device.id"
        class="device card"
        :class="{ offline: !device.online }"
      >
        <div class="top">
          <span class="index mono">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="status" :class="device.online ? 'ok' : ''">
            {{ device.online ? 'Online' : 'Offline' }}
          </span>
        </div>

        <h3 class="name">{{ device.name }}</h3>

        <div class="meta">
          <div class="meta-cell">
            <span class="meta-label mono">Firmware</span>
            <span class="meta-value mono">{{ device.firmware }}</span>
          </div>
          <div class="meta-cell">
            <span class="meta-label mono">Battery</span>
            <span class="meta-value mono">{{ device.battery }}%</span>
          </div>
          <div class="meta-cell">
            <span class="meta-label mono">Location</span>
            <span class="meta-value">{{ device.location ?? '未登记' }}</span>
          </div>
          <div class="meta-cell">
            <span class="meta-label mono">Heartbeat</span>
            <span class="meta-value">{{ formatRelative(device.last_heartbeat) }}</span>
          </div>
        </div>

        <div class="foot">
          <span class="heart mono">{{ formatDateTime(device.last_heartbeat) }}</span>
          <el-button class="enter" @click="enter(device)">
            进入控制台 <span class="arrow">↗</span>
          </el-button>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.ghost {
  border-color: var(--hair);
  background: transparent;
  color: var(--ink);
}

.ghost:hover {
  border-color: var(--ink);
  background: transparent;
  color: var(--ink);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(460px, 1fr));
  gap: 14px;
}

.device {
  display: flex;
  flex-direction: column;
  padding: 16px 18px 14px;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}

.device:hover {
  border-color: rgba(20, 20, 20, 0.36);
}

.device.offline {
  background: rgba(247, 244, 238, 0.6);
}

.device.offline .name {
  color: var(--dim);
}

.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.index {
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--faint);
}

.name {
  margin: 10px 0 14px;
  font-size: 18px;
  font-weight: 500;
  letter-spacing: -0.01em;
}

.meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--hair-soft);
  border: 1px solid var(--hair-soft);
}

.meta-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 11px;
  background: var(--panel);
}

.meta-label {
  font-size: 8px;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--faint);
}

.meta-value {
  font-size: 12.5px;
  font-weight: 500;
}

.foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--hair-soft);
}

.heart {
  font-size: 8.5px;
  letter-spacing: 0.06em;
  color: var(--faint);
}

.enter {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--ink);
  background: transparent;
  color: var(--ink);
  font-size: 12px;
  letter-spacing: 0.03em;
}

.enter:hover {
  background: var(--ink);
  color: var(--paper);
  border-color: var(--ink);
}

.enter:disabled {
  border-color: var(--hair);
  background: transparent;
  color: var(--faint);
}

.arrow {
  font-family: var(--mono);
  margin-left: 4px;
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
