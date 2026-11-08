<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { EditPen, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import EmptyState from '@/components/EmptyState.vue'
import PetCharm from '@/components/PetCharm.vue'
import type { Device } from '@/types'
import { formatDateTime, formatRelative } from '@/utils/format'
import { useDeviceStore } from '@/stores/device'

const router = useRouter()
const deviceStore = useDeviceStore()

const renameVisible = ref(false)
const renameValue = ref('')
const renameSaving = ref(false)
let renameTarget: Device | null = null

onMounted(() => {
  if (!deviceStore.loaded) void deviceStore.load()
})

function enter(device: Device): void {
  deviceStore.select(device.id)
  void router.push('/console')
}

function refresh(): void {
  void deviceStore.load()
}

function openRename(device: Device): void {
  renameTarget = device
  renameValue.value = device.name
  renameVisible.value = true
}

async function submitRename(): Promise<void> {
  const name = renameValue.value.trim()
  if (!name) {
    ElMessage.warning('名字不能为空')
    return
  }
  if (name.length > 20) {
    ElMessage.warning('名字不能超过 20 个字符')
    return
  }
  if (!renameTarget) return

  renameSaving.value = true
  try {
    await deviceStore.rename(renameTarget.id, name)
    ElMessage.success('名字已更新')
    renameVisible.value = false
  } catch {
    // 错误提示由 request 层统一弹出
  } finally {
    renameSaving.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <div class="page-kicker">02 / Devices</div>
        <h2 class="page-title">我的设备</h2>
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

        <div class="name-row">
          <h3 class="name" :title="device.name">{{ device.name }}</h3>
          <PetCharm class="charm" :online="device.online" />
          <button type="button" class="rename" title="修改桌宠名字" @click="openRename(device)">
            <el-icon><EditPen /></el-icon>
          </button>
        </div>

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
          <el-button class="enter" :disabled="!device.online" @click="enter(device)">
            进入控制台 <span class="arrow">↗</span>
          </el-button>
        </div>
      </article>
    </div>

    <el-dialog v-model="renameVisible" title="修改桌宠名字" width="380px">
      <div class="rename-body">
        <span class="field-label mono">Pet name</span>
        <el-input
          v-model="renameValue"
          maxlength="20"
          show-word-limit
          placeholder="给桌宠起个名字"
          autofocus
          @keyup.enter="submitRename"
        />
        <p class="rename-hint">1–20 个字符，保存后同步到设备列表。</p>
      </div>
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" :loading="renameSaving" @click="submitRename">保存</el-button>
      </template>
    </el-dialog>
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

.name-row {
  display: flex;
  align-items: flex-start;
  min-height: 64px;
  margin: 4px 0 8px;
}

.name {
  max-width: calc(100% - 114px);
  padding-top: 9px;
  overflow: hidden;
  font-size: 18px;
  font-weight: 500;
  letter-spacing: -0.01em;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.charm {
  margin: -6px 0 0 8px;
}

.rename {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin: 8px 0 0 3px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: var(--radius);
  background: transparent;
  color: var(--faint);
  opacity: 0.6;
  cursor: pointer;
  transition:
    opacity 0.16s ease,
    color 0.16s ease,
    border-color 0.16s ease;
}

.device:hover .rename {
  opacity: 1;
}

.rename:hover {
  border-color: var(--hair);
  color: var(--ink);
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

.rename-body {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.field-label {
  font-size: 8px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.rename-hint {
  font-size: 11px;
  color: var(--faint);
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
