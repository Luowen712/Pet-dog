<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, Upload } from '@element-plus/icons-vue'
import FaceTile from '@/components/FaceTile.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { FaceItem } from '@/types'
import { deleteFace, listFaces, uploadFace } from '@/api/face'
import { usePetStore } from '@/stores/pet'

const pet = usePetStore()

const faces = ref<FaceItem[]>([])
const loading = ref(false)
const fileInput = ref<HTMLInputElement>()

const builtin = computed(() => faces.value.filter((face) => face.builtin))
const custom = computed(() => faces.value.filter((face) => !face.builtin))

async function load(): Promise<void> {
  loading.value = true
  try {
    faces.value = await listFaces()
  } finally {
    loading.value = false
  }
}

function pickFile(): void {
  fileInput.value?.click()
}

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size !== 512) {
    ElMessage.error(`图片必须正好 512 字节（128×32 单色位图），当前 ${file.size} 字节`)
    return
  }
  try {
    const item = await uploadFace(file)
    faces.value.push(item)
    ElMessage.success('上传成功')
  } catch {
    // 错误提示由 request 层统一弹出
  }
}

async function remove(face: FaceItem): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除表情「${face.name}」吗？`, '删除表情', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteFace(face.id)
    faces.value = faces.value.filter((item) => item.id !== face.id)
    ElMessage.success('已删除')
  } catch {
    // 已统一提示
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <div class="page-kicker">06 / Faces</div>
        <h2 class="page-title">表情库</h2>
        <p class="page-sub">7 张内置表情 + 自定义上传，点卡片立即切换屏幕上的脸</p>
      </div>
      <div class="head-actions">
        <el-button class="ghost" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :icon="Upload" @click="pickFile">上传表情</el-button>
        <input ref="fileInput" type="file" accept="image/*" class="hidden-input" @change="onFile" />
      </div>
    </div>

    <section class="card" v-loading="loading">
      <div class="card-head">
        <span class="card-title">内置表情</span>
        <span class="card-meta">07 built-in · face id 0–6</span>
      </div>
      <div class="grid">
        <button
          v-for="face in builtin"
          :key="face.id"
          type="button"
          class="face-card"
          :class="{ active: pet.face === face.id }"
          @click="pet.changeFace(face.id)"
        >
          <FaceTile :face="face.id" />
          <span class="meta">
            <span class="name">{{ face.name }}</span>
            <span class="mono id">0{{ face.id }}</span>
          </span>
        </button>
      </div>
    </section>

    <section class="card" v-loading="loading">
      <div class="card-head">
        <span class="card-title">自定义表情</span>
        <span class="card-meta">PNG 128×32 mono · exactly 512 bytes</span>
      </div>

      <div v-if="custom.length > 0" class="grid">
        <div
          v-for="face in custom"
          :key="face.id"
          class="face-card custom"
          :class="{ active: pet.face === face.id }"
          @click="pet.changeFace(face.id)"
        >
          <img v-if="face.preview" :src="face.preview" class="preview" :alt="face.name" />
          <div v-else class="preview placeholder mono">128 × 32</div>
          <span class="meta">
            <span class="name">{{ face.name }}</span>
            <el-button
              link
              type="danger"
              :icon="Delete"
              class="del"
              title="删除表情"
              @click.stop="remove(face)"
            />
          </span>
        </div>
      </div>

      <EmptyState
        v-else
        title="还没有自定义表情，点右上角上传一张"
        hint="Upload 512-byte png"
      />
    </section>
  </div>
</template>

<style scoped>
.head-actions {
  display: flex;
  gap: 10px;
}

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

.hidden-input {
  display: none;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 12px;
  padding: 16px 20px 20px;
}

.face-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--hair-soft);
  border-radius: var(--radius);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;
}

.face-card:hover {
  border-color: rgba(20, 20, 20, 0.32);
}

.face-card.active {
  border-color: var(--ink);
  background: rgba(255, 255, 255, 0.42);
}

.meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 2px;
}

.name {
  font-size: 12px;
  font-weight: 500;
  color: var(--dim);
}

.face-card.active .name {
  color: var(--ink);
}

.id {
  font-size: 8.5px;
  color: var(--faint);
  letter-spacing: 0.08em;
}

.preview {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 4 / 1;
  object-fit: cover;
  border-radius: 1px;
  background: #0a0f1a;
  border: 1px solid rgba(20, 20, 20, 0.55);
}

.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.4);
  font-size: 10px;
  letter-spacing: 0.12em;
}

.del {
  padding: 0;
  height: auto;
}
</style>
