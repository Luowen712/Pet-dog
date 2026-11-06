<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowUp, Delete, Plus, VideoPlay } from '@element-plus/icons-vue'
import type { Scene } from '@/types'
import EmptyState from '@/components/EmptyState.vue'
import { createScene, deleteScene, listScenes, runScene, updateScene } from '@/api/scene'
import { ACTION_GROUPS, actionHex, actionsOf } from '@/constants/actions'

const scenes = ref<Scene[]>([])
const selectedId = ref<number | null>(null)
const draft = ref<Scene | null>(null)

const loading = ref(false)
const saving = ref(false)
const creating = ref(false)
const dialogVisible = ref(false)
const newName = ref('')
const newDesc = ref('')

async function load(): Promise<void> {
  loading.value = true
  try {
    scenes.value = await listScenes()
    if (selectedId.value && scenes.value.some((scene) => scene.id === selectedId.value)) {
      select(selectedId.value)
    } else if (scenes.value.length > 0) {
      select(scenes.value[0].id)
    } else {
      selectedId.value = null
      draft.value = null
    }
  } finally {
    loading.value = false
  }
}

function select(id: number): void {
  selectedId.value = id
  const found = scenes.value.find((scene) => scene.id === id)
  draft.value = found ? (JSON.parse(JSON.stringify(found)) as Scene) : null
}

function openCreate(): void {
  newName.value = ''
  newDesc.value = ''
  dialogVisible.value = true
}

async function confirmCreate(): Promise<void> {
  if (!newName.value.trim()) {
    ElMessage.warning('场景名不能为空')
    return
  }
  creating.value = true
  try {
    const created = await createScene({
      name: newName.value.trim(),
      description: newDesc.value.trim(),
      steps: [{ action: 0x31 }],
    })
    dialogVisible.value = false
    await load()
    select(created.id)
    ElMessage.success('场景已创建')
  } catch {
    // 已统一提示
  } finally {
    creating.value = false
  }
}

function addStep(): void {
  draft.value?.steps.push({ action: 0x31 })
}

function removeStep(index: number): void {
  draft.value?.steps.splice(index, 1)
}

function move(index: number, direction: -1 | 1): void {
  const steps = draft.value?.steps
  if (!steps) return
  const target = index + direction
  if (target < 0 || target >= steps.length) return
  const [item] = steps.splice(index, 1)
  steps.splice(target, 0, item)
}

async function save(): Promise<boolean> {
  const current = draft.value
  if (!current) return false
  if (!current.name.trim()) {
    ElMessage.warning('场景名不能为空')
    return false
  }
  if (current.steps.length === 0) {
    ElMessage.warning('至少需要一个步骤')
    return false
  }

  saving.value = true
  try {
    if (current.id) {
      await updateScene(current.id, {
        name: current.name,
        description: current.description,
        steps: current.steps,
      })
    } else {
      const created = await createScene({
        name: current.name,
        description: current.description,
        steps: current.steps,
      })
      current.id = created.id
    }
    ElMessage.success('已保存')
    const id = current.id
    await load()
    if (id) select(id)
    return true
  } catch {
    return false
  } finally {
    saving.value = false
  }
}

async function run(): Promise<void> {
  if (!draft.value) return
  const ok = await save()
  if (!ok) return
  const scene = draft.value
  if (!scene?.id) return
  try {
    const result = await runScene(scene.id)
    ElMessage.success(`开始执行「${scene.name}」，共 ${result.steps} 步`)
  } catch {
    // 已统一提示
  }
}

async function removeScene(scene: Scene): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除场景「${scene.name}」吗？`, '删除场景', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteScene(scene.id)
    if (selectedId.value === scene.id) {
      selectedId.value = null
      draft.value = null
    }
    await load()
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
        <div class="page-kicker">07 / Scenes</div>
        <h2 class="page-title">场景编排</h2>
        <p class="page-sub">把几个动作串成一场戏，保存后一键执行</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建场景</el-button>
    </div>

    <div class="layout">
      <section class="card list-card" v-loading="loading">
        <div class="card-head">
          <span class="card-title">场景</span>
          <span class="card-meta">{{ scenes.length }} total</span>
        </div>

        <div v-if="scenes.length > 0" class="scene-list">
          <button
            v-for="(scene, index) in scenes"
            :key="scene.id"
            type="button"
            class="scene-item"
            :class="{ active: selectedId === scene.id }"
            @click="select(scene.id)"
          >
            <span class="scene-index mono">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="scene-body">
              <span class="scene-name">{{ scene.name }}</span>
              <span class="scene-sub mono">
                {{ scene.steps.length }} steps · {{ scene.description || 'no description' }}
              </span>
            </span>
            <el-button
              link
              type="danger"
              :icon="Delete"
              class="scene-del"
              title="删除场景"
              @click.stop="removeScene(scene)"
            />
          </button>
        </div>

        <EmptyState v-else title="还没有场景，新建一个" hint="No scenes" />
      </section>

      <section class="card editor-card" v-loading="loading">
        <template v-if="draft">
          <div class="card-head">
            <span class="card-title">步骤编辑器</span>
            <span class="card-meta">{{ draft.steps.length }} steps</span>
          </div>

          <div class="editor-body">
            <div class="editor-fields">
              <label class="field">
                <span class="field-label mono">Scene name</span>
                <el-input v-model="draft.name" maxlength="20" />
              </label>
              <label class="field">
                <span class="field-label mono">Description</span>
                <el-input v-model="draft.description" maxlength="60" placeholder="可选" />
              </label>
            </div>

            <div class="steps">
              <div class="steps-head">
                <span class="mono">Steps</span>
                <el-button size="small" :icon="Plus" @click="addStep">加一步</el-button>
              </div>

              <div v-if="draft.steps.length === 0" class="empty-steps">
                还没有步骤，点「加一步」开始排
              </div>

              <div v-for="(step, index) in draft.steps" :key="index" class="step">
                <span class="step-index mono">{{ String(index + 1).padStart(2, '0') }}</span>
                <el-select v-model="step.action" class="step-select">
                  <el-option-group v-for="group in ACTION_GROUPS" :key="group" :label="group">
                    <el-option
                      v-for="action in actionsOf(group)"
                      :key="action.code"
                      :label="action.name"
                      :value="action.code"
                    >
                      <span class="option">
                        <span>{{ action.name }}</span>
                        <span class="mono faint">{{ actionHex(action.code) }}</span>
                      </span>
                    </el-option>
                  </el-option-group>
                </el-select>
                <span class="step-code mono">{{ actionHex(step.action) }}</span>
                <div class="step-actions">
                  <el-button
                    link
                    :icon="ArrowUp"
                    :disabled="index === 0"
                    title="上移"
                    @click="move(index, -1)"
                  />
                  <el-button
                    link
                    :icon="ArrowDown"
                    :disabled="index === draft.steps.length - 1"
                    title="下移"
                    @click="move(index, 1)"
                  />
                  <el-button
                    link
                    type="danger"
                    :icon="Delete"
                    title="删除这一步"
                    @click="removeStep(index)"
                  />
                </div>
              </div>
            </div>
          </div>

          <div class="editor-foot">
            <span class="scene-ref mono">SCENE {{ draft.id ? `#${draft.id}` : 'NEW' }}</span>
            <div class="foot-actions">
              <el-button :loading="saving" @click="save">保存</el-button>
              <el-button type="primary" :loading="saving" :icon="VideoPlay" @click="run">
                保存并执行
              </el-button>
            </div>
          </div>
        </template>

        <EmptyState v-else title="从左边选一个场景，或新建一个" hint="No scene selected" />
      </section>
    </div>

    <el-dialog v-model="dialogVisible" title="新建场景" width="420px">
      <el-form label-position="top">
        <el-form-item label="场景名">
          <el-input v-model="newName" placeholder="例如：早上好" maxlength="20" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="newDesc" placeholder="可选" maxlength="60" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="confirmCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.list-card {
  overflow: hidden;
}

.scene-list {
  display: flex;
  flex-direction: column;
}

.scene-item {
  position: relative;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 14px;
  border: 0;
  border-bottom: 1px solid var(--hair-soft);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background 0.16s ease;
}

.scene-item:last-child {
  border-bottom: 0;
}

.scene-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--ink);
  opacity: 0;
}

.scene-item:hover {
  background: rgba(20, 20, 20, 0.025);
}

.scene-item.active {
  background: rgba(255, 255, 255, 0.55);
}

.scene-item.active::before {
  opacity: 1;
}

.scene-index {
  font-size: 9px;
  letter-spacing: 0.08em;
  color: var(--faint);
}

.scene-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.scene-name {
  font-size: 13.5px;
  font-weight: 500;
}

.scene-sub {
  font-size: 8.5px;
  letter-spacing: 0.04em;
  color: var(--faint);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.scene-del {
  opacity: 0;
  transition: opacity 0.15s ease;
}

.scene-item:hover .scene-del {
  opacity: 1;
}

.editor-card {
  min-height: 420px;
}

.editor-body {
  padding: 18px 20px 6px;
}

.editor-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 22px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.field-label {
  font-size: 8px;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--faint);
}

.steps-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 9px;
  border-bottom: 1px solid var(--hair);
  font-size: 8.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.empty-steps {
  padding: 26px;
  text-align: center;
  font-size: 12px;
  color: var(--faint);
  border-bottom: 1px dashed var(--hair);
}

.step {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--hair-soft);
}

.step-index {
  font-size: 9px;
  letter-spacing: 0.08em;
  color: var(--faint);
  width: 18px;
  flex-shrink: 0;
}

.step-select {
  flex: 1;
  min-width: 0;
}

.step-code {
  width: 40px;
  flex-shrink: 0;
  font-size: 9.5px;
  letter-spacing: 0.04em;
  color: var(--faint);
}

.step-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.editor-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px 16px;
  border-top: 1px solid var(--hair);
}

.scene-ref {
  font-size: 8px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.foot-actions {
  display: flex;
  gap: 8px;
}

@media (max-width: 980px) {
  .layout {
    grid-template-columns: 1fr;
  }

  .editor-fields {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .step-code {
    display: none;
  }
}
</style>
