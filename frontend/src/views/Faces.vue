<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Refresh } from '@element-plus/icons-vue'
import FaceTile from '@/components/FaceTile.vue'
import type { FaceItem } from '@/types'
import { listFaces } from '@/api/face'
import { describeDeviceStatus } from '@/utils/format'
import { emitParticleBurst } from '@/utils/theme'
import { useDeviceStore } from '@/stores/device'
import { usePetStore } from '@/stores/pet'

const deviceStore = useDeviceStore()
const pet = usePetStore()

const faces = ref<FaceItem[]>([])
const loading = ref(false)
const selectedId = ref<number | null>(null)

const builtin = computed(() => faces.value.filter((face) => face.builtin))

const selectedIndex = computed(() => {
  if (builtin.value.length === 0) return -1
  const idx = builtin.value.findIndex((face) => face.id === selectedId.value)
  return idx >= 0 ? idx : 0
})

const selectedFace = computed<FaceItem | null>(() =>
  selectedIndex.value >= 0 ? builtin.value[selectedIndex.value] : null,
)

const activeFace = computed<FaceItem | null>(
  () => builtin.value.find((face) => face.id === pet.face) ?? null,
)

const statusView = computed(() =>
  describeDeviceStatus({
    online: pet.online,
    controlState: pet.controlState,
  }),
)

const canApply = computed(
  () =>
    !!deviceStore.current &&
    pet.connected &&
    pet.online &&
    ['ready', 'busy'].includes(pet.controlState) &&
    pet.switchingFace === null,
)

const needsReconnect = computed(
  () => !!deviceStore.current && (!pet.online || pet.controlState === 'faulted'),
)

async function load(): Promise<void> {
  loading.value = true
  try {
    faces.value = await listFaces()
    if (selectedId.value === null && builtin.value.length > 0) {
      const currentExists = builtin.value.some((face) => face.id === pet.face)
      selectedId.value = currentExists && pet.face !== null ? pet.face : builtin.value[0].id
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => pet.face,
  (faceId) => {
    if (selectedId.value === null && faceId !== null && builtin.value.some((f) => f.id === faceId)) {
      selectedId.value = faceId
    }
  },
)

function step(delta: number): void {
  const list = builtin.value
  if (list.length === 0) return
  const next = (selectedIndex.value + delta + list.length) % list.length
  selectedId.value = list[next].id
}

function selectFace(id: number): void {
  selectedId.value = id
}

async function applyFace(id: number, event?: MouseEvent): Promise<void> {
  if (event && event.clientX > 0) emitParticleBurst(event.clientX, event.clientY, 'oled', 16)
  selectedId.value = id
  await pet.changeFace(id)
}

function onKeydown(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
  if (event.key === 'ArrowLeft') step(-1)
  if (event.key === 'ArrowRight') step(1)
}

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div class="head-left">
        <router-link to="/console" class="back-link">
          <el-icon><ArrowLeft /></el-icon>
          <span>返回控制台</span>
        </router-link>
        <div class="title-row">
          <h2 class="page-title">表情库</h2>
          <span v-if="deviceStore.current" class="status" :class="statusView.tone">
            {{ statusView.label }}
          </span>
        </div>
      </div>

      <div class="head-actions">
        <router-link v-if="needsReconnect" to="/devices">
          <el-button size="small">重连蓝牙</el-button>
        </router-link>
        <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <section v-if="selectedFace" class="card preview-stage">
      <div class="preview-bezel">
        <FaceTile :face="selectedFace.id" class="preview-screen" />
      </div>

      <div class="preview-info">
        <div class="preview-head">
          <h3 class="preview-name">{{ selectedFace.name }}</h3>
          <span v-if="pet.face === selectedFace.id" class="current-tag">当前使用</span>
        </div>

        <div class="preview-actions">
          <el-button
            v-if="deviceStore.current"
            type="primary"
            :disabled="!canApply"
            :loading="pet.switchingFace === selectedFace.id"
            @click="applyFace(selectedFace.id, $event)"
          >
            {{ pet.face === selectedFace.id ? '重新下发' : '应用到桌宠' }}
          </el-button>
          <router-link v-else to="/devices">
            <el-button type="primary">去连接蓝牙设备</el-button>
          </router-link>

          <div class="step-group">
            <el-button :icon="ArrowLeft" title="上一个" @click="step(-1)" />
            <el-button :icon="ArrowRight" title="下一个" @click="step(1)" />
          </div>
        </div>
      </div>
    </section>

    <section class="card" v-loading="loading">
      <div class="card-head">
        <span class="card-title">内置表情</span>
        <span v-if="activeFace" class="active-label">当前：{{ activeFace.name }}</span>
      </div>

      <div class="grid">
        <div
          v-for="face in builtin"
          :key="face.id"
          role="button"
          tabindex="0"
          class="face-card"
          :class="{
            selected: selectedFace?.id === face.id,
            active: pet.face === face.id,
            sending: pet.switchingFace === face.id,
          }"
          @click="selectFace(face.id)"
          @dblclick="canApply && applyFace(face.id, $event)"
          @keydown.enter.prevent="selectFace(face.id)"
          @keydown.space.prevent="selectFace(face.id)"
        >
          <FaceTile :face="face.id" />
          <div class="face-foot">
            <span class="name">
              <span v-if="pet.face === face.id" class="dot ok" />
              {{ face.name }}
            </span>
            <button
              v-if="canApply"
              type="button"
              class="quick-apply"
              @click.stop="applyFace(face.id, $event)"
            >
              应用
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.head-left {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  width: fit-content;
  font-size: 12px;
  color: var(--dim);
  transition: color 0.16s ease;
}

.back-link:hover {
  color: var(--ink);
}

.title-row {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.preview-stage {
  display: grid;
  grid-template-columns: minmax(260px, 460px) minmax(0, 1fr);
  gap: 28px;
  align-items: center;
  padding: 24px 26px;
  background: var(--bg-stage);
}

.preview-bezel {
  position: relative;
  z-index: 1;
  padding: 16px;
  border-radius: var(--radius-md);
  background: var(--oled-bg);
  border: 1px solid var(--oled-screen-border);
  box-shadow: var(--shadow-sm);
}

.preview-screen {
  width: 100%;
}

.preview-info {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.preview-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.preview-name {
  font-size: 26px;
  font-weight: 600;
}

.current-tag {
  padding: 3px 10px;
  border: 1px solid var(--ok-border);
  border-radius: var(--radius-pill);
  background: var(--ok-soft);
  font-size: 11.5px;
  font-weight: 500;
  color: var(--ok);
}

.preview-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.step-group {
  display: inline-flex;
  gap: 6px;
}

.active-label {
  font-size: 12px;
  color: var(--dim);
}

.grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  padding: 18px 20px 20px;
}

.face-card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 10px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-md);
  background: var(--surface-2);
  cursor: pointer;
  outline: none;
  transition:
    border-color 0.18s var(--ease-out),
    background-color 0.18s var(--ease-out),
    transform 0.18s var(--ease-out);
}

.face-card:hover,
.face-card:focus-visible {
  border-color: var(--hair-strong);
  transform: translateY(-2px);
}

.face-card.selected {
  border-color: var(--accent-border);
  background: var(--accent-soft);
}

.face-card.sending {
  border-color: var(--warn-border);
  background: var(--warn-soft);
}

.face-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 2px;
}

.name {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--dim);
}

.face-card.selected .name,
.face-card.active .name {
  color: var(--ink);
}

.quick-apply {
  padding: 3px 9px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-xs);
  background: var(--surface-3);
  font-family: var(--sans);
  font-size: 11px;
  color: var(--dim);
  white-space: nowrap;
  cursor: pointer;
  opacity: 0;
  transition:
    opacity 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}

.face-card:hover .quick-apply,
.face-card.selected .quick-apply,
.quick-apply:focus-visible {
  opacity: 1;
}

.quick-apply:hover {
  border-color: var(--hair-strong);
  color: var(--ink);
}

@media (max-width: 820px) {
  .preview-stage {
    grid-template-columns: 1fr;
    gap: 18px;
    padding: 18px;
  }

  .quick-apply {
    opacity: 1;
  }
}
</style>
