<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  DArrowLeft,
  DArrowRight,
  Headset,
  SwitchButton,
  VideoPause,
  VideoPlay,
} from '@element-plus/icons-vue'
import {
  MUSIC_NEXT,
  MUSIC_PAUSE,
  MUSIC_PLAY,
  MUSIC_PREV,
  MUSIC_STOP,
  MUSIC_VOLUME,
} from '@/api/music'
import { formatTrack } from '@/utils/format'
import { useDeviceStore } from '@/stores/device'
import { usePetStore } from '@/stores/pet'

const pet = usePetStore()
const deviceStore = useDeviceStore()

const volume = ref(pet.volume)

watch(
  () => pet.volume,
  (value) => {
    volume.value = value
  },
)

const deviceId = computed(() => deviceStore.currentId || 1)
const stateText = computed(() => {
  if (pet.musicState === 1) return 'PLAYING'
  if (pet.musicState === 2) return 'PAUSED'
  return 'STOPPED'
})

function send(command: number, value = 0): void {
  void pet.controlMusic(command, value, deviceId.value)
}

function onVolumeChange(value: number | number[]): void {
  const next = Array.isArray(value) ? value[0] : value
  volume.value = next
  send(MUSIC_VOLUME, next)
}
</script>

<template>
  <div class="music card">
    <div class="head">
      <span class="card-title">音乐播放器</span>
      <span class="status" :class="{ ok: pet.musicState === 1 }">{{ stateText }}</span>
    </div>

    <div class="track">
      <span class="track-label mono">Track</span>
      <span class="track-num mono">{{ formatTrack(pet.track) }}</span>
      <span class="track-total mono">/ 09</span>
    </div>

    <div class="controls">
      <el-button class="ctrl" circle title="上一首" @click="send(MUSIC_PREV)">
        <el-icon><DArrowLeft /></el-icon>
      </el-button>
      <el-button class="ctrl play" type="primary" circle title="播放" @click="send(MUSIC_PLAY)">
        <el-icon><VideoPlay /></el-icon>
      </el-button>
      <el-button class="ctrl" circle title="暂停" @click="send(MUSIC_PAUSE)">
        <el-icon><VideoPause /></el-icon>
      </el-button>
      <el-button class="ctrl" circle title="停止" @click="send(MUSIC_STOP)">
        <el-icon><SwitchButton /></el-icon>
      </el-button>
      <el-button class="ctrl" circle title="下一首" @click="send(MUSIC_NEXT)">
        <el-icon><DArrowRight /></el-icon>
      </el-button>
    </div>

    <div class="volume">
      <el-icon class="volume-icon"><Headset /></el-icon>
      <el-slider
        v-model="volume"
        :min="0"
        :max="30"
        :step="1"
        :show-tooltip="true"
        class="volume-slider"
        @change="onVolumeChange"
      />
      <span class="volume-num mono">{{ volume }}</span>
    </div>
  </div>
</template>

<style scoped>
.music {
  padding: 17px 20px 14px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.status {
  font-size: 8.5px;
  letter-spacing: 0.12em;
}

.track {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 16px 0 14px;
}

.track-label {
  font-size: 8.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.track-num {
  font-size: 34px;
  font-weight: 300;
  letter-spacing: 0.08em;
  line-height: 1;
}

.track-total {
  font-size: 10px;
  color: var(--faint);
}

.controls {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ctrl {
  width: 36px;
  height: 32px;
  margin: 0;
  border-color: var(--hair);
  color: var(--dim);
}

.ctrl:hover {
  color: var(--ink);
  border-color: rgba(20, 20, 20, 0.35);
  background: transparent;
}

.ctrl.play {
  width: 42px;
  height: 32px;
  color: var(--paper);
}

.ctrl.play:hover {
  background: #000;
  border-color: #000;
  color: var(--paper);
}

.volume {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  padding-top: 13px;
  border-top: 1px solid var(--hair-soft);
}

.volume-icon {
  color: var(--faint);
  font-size: 14px;
}

.volume-slider {
  flex: 1;
}

.volume-num {
  width: 20px;
  text-align: right;
  font-size: 10px;
  color: var(--dim);
}
</style>
