<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useTheme } from '@/utils/theme'

const props = withDefaults(defineProps<{ online?: boolean }>(), { online: true })

const canvasRef = ref<HTMLCanvasElement | null>(null)
const { theme } = useTheme()

let rafId = 0
let observer: ResizeObserver | null = null

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas || typeof window === 'undefined') return
  if (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent)) return

  let ctx: CanvasRenderingContext2D | null = null
  try {
    ctx = canvas.getContext('2d')
  } catch {
    return
  }
  if (!ctx) return

  const context = ctx
  let width = 180
  let height = 30
  let dpr = 1
  let phase = 0
  const reduced = Boolean(
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  function syncSize(): void {
    const parent = canvas?.parentElement
    if (!canvas || !parent) return
    const rect = parent.getBoundingClientRect()
    width = Math.max(100, Math.floor(rect.width || 180))
    height = Math.max(24, Math.floor(rect.height || 30))
    dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = width * dpr
    canvas.height = height * dpr
    context.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  function render(): void {
    context.clearRect(0, 0, width, height)
    const rgb: [number, number, number] = props.online
      ? theme.value === 'phosphor'
        ? [94, 242, 184]
        : [33, 115, 79]
      : [148, 148, 148]

    context.beginPath()
    context.lineWidth = 1.6
    context.strokeStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${props.online ? 0.9 : 0.35})`

    const mid = height * 0.56
    for (let x = 0; x < width; x++) {
      let y = mid
      if (props.online) {
        const t = ((x + phase) % 72) / 72
        if (t > 0.42 && t < 0.47) y = mid - 3
        else if (t >= 0.47 && t < 0.52) y = mid + 5
        else if (t >= 0.52 && t < 0.57) y = mid - height * 0.4
        else if (t >= 0.57 && t < 0.62) y = mid + 6
        else if (t >= 0.62 && t < 0.68) y = mid - 3
        else y = mid + Math.sin((x + phase) * 0.08) * 0.7
      }
      if (x === 0) context.moveTo(x, y)
      else context.lineTo(x, y)
    }
    context.stroke()

    if (!reduced) {
      if (props.online) phase += 0.85
      rafId = window.requestAnimationFrame(render)
    }
  }

  syncSize()
  if (typeof ResizeObserver !== 'undefined' && canvas.parentElement) {
    observer = new ResizeObserver(syncSize)
    observer.observe(canvas.parentElement)
  }
  render()
})

onBeforeUnmount(() => {
  if (rafId && typeof window !== 'undefined') window.cancelAnimationFrame(rafId)
  observer?.disconnect()
})
</script>

<template>
  <div class="hb-wrap" aria-hidden="true">
    <canvas ref="canvasRef" class="hb-canvas" />
  </div>
</template>

<style scoped>
.hb-wrap {
  width: 100%;
  height: 30px;
  border-radius: var(--radius-xs);
  background: var(--surface-2);
  border: 1px solid var(--hair-soft);
  overflow: hidden;
}

.hb-canvas {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
