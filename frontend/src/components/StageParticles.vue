<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useTheme } from '@/utils/theme'
import type { ThemeId } from '@/utils/theme'

const props = withDefaults(defineProps<{ online?: boolean; busy?: boolean }>(), {
  online: true,
  busy: false,
})

interface OrbitNode {
  angle: number
  rx: number
  ry: number
  yOff: number
  speed: number
  r: number
  alt: boolean
}

const PALETTES: Record<ThemeId, { a: [number, number, number]; b: [number, number, number] }> = {
  porcelain: { a: [230, 84, 59], b: [235, 142, 42] },
  phosphor: { a: [94, 242, 184], b: [255, 179, 71] },
}

const canvasRef = ref<HTMLCanvasElement | null>(null)
const { theme } = useTheme()

let rafId = 0
let observer: ResizeObserver | null = null

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas || typeof window === 'undefined') return
  if (typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent)) return
  if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

  let ctx: CanvasRenderingContext2D | null = null
  try {
    ctx = canvas.getContext('2d')
  } catch {
    return
  }
  if (!ctx) return

  const context = ctx
  let width = 560
  let height = 360
  let dpr = 1

  const nodes: OrbitNode[] = Array.from({ length: 34 }, (_, i) => ({
    angle: Math.random() * Math.PI * 2,
    rx: 92 + Math.random() * 140,
    ry: 20 + Math.random() * 34,
    yOff: (Math.random() - 0.5) * 140,
    speed: 0.004 + Math.random() * 0.007,
    r: 1.2 + Math.random() * 1.9,
    alt: i % 3 === 0,
  }))

  function syncSize(): void {
    const parent = canvas?.parentElement
    if (!canvas || !parent) return
    const rect = parent.getBoundingClientRect()
    width = Math.max(240, Math.floor(rect.width || 560))
    height = Math.max(200, Math.floor(rect.height || 360))
    dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = width * dpr
    canvas.height = height * dpr
    context.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  function render(): void {
    context.clearRect(0, 0, width, height)
    const pal = PALETTES[theme.value]
    const cx = width * 0.5
    const cy = height * 0.56
    const speedMul = !props.online ? 0.18 : props.busy ? 2.4 : 1

    context.save()
    context.strokeStyle = `rgba(${pal.a[0]},${pal.a[1]},${pal.a[2]},${props.online ? 0.16 : 0.06})`
    context.lineWidth = 1
    context.beginPath()
    context.ellipse(cx, cy + 52, Math.min(156, width * 0.34), 26, 0, 0, Math.PI * 2)
    context.stroke()
    context.restore()

    for (const n of nodes) {
      n.angle += n.speed * speedMul
      const px = cx + Math.cos(n.angle) * Math.min(n.rx, width * 0.44)
      const py = cy + Math.sin(n.angle) * n.ry + n.yOff * 0.42 + Math.sin(n.angle * 2) * 7
      const rgb = n.alt ? pal.b : pal.a
      const alpha = (0.18 + 0.48 * ((Math.sin(n.angle) + 1) * 0.5)) * (props.online ? 1 : 0.32)

      context.beginPath()
      context.arc(px, py, n.r, 0, Math.PI * 2)
      context.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha.toFixed(3)})`
      context.fill()
    }

    rafId = window.requestAnimationFrame(render)
  }

  syncSize()
  if (typeof ResizeObserver !== 'undefined' && canvas.parentElement) {
    observer = new ResizeObserver(syncSize)
    observer.observe(canvas.parentElement)
  }
  rafId = window.requestAnimationFrame(render)
})

onBeforeUnmount(() => {
  if (rafId && typeof window !== 'undefined') window.cancelAnimationFrame(rafId)
  observer?.disconnect()
})
</script>

<template>
  <canvas ref="canvasRef" class="stage-particles" aria-hidden="true" />
</template>

<style scoped>
.stage-particles {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}
</style>
