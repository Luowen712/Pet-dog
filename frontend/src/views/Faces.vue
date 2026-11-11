<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import FaceTile from '@/components/FaceTile.vue'
import type { FaceItem } from '@/types'
import { listFaces } from '@/api/face'
import { usePetStore } from '@/stores/pet'

const pet = usePetStore()

const faces = ref<FaceItem[]>([])
const loading = ref(false)

const builtin = computed(() => faces.value.filter((face) => face.builtin))

async function load(): Promise<void> {
  loading.value = true
  try {
    faces.value = await listFaces()
  } finally {
    loading.value = false
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
        <p class="page-sub">只保留 7 张内置表情；自定义上传/删除本期关闭</p>
      </div>
      <el-button class="ghost" :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
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
</style>
