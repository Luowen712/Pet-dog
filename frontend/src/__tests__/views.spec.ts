import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import App from '@/App.vue'
import router from '@/router'

vi.mock('echarts', () => {
  const chart = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  }
  return {
    init: vi.fn(() => chart),
    getInstanceByDom: vi.fn(() => null),
    graphic: {
      LinearGradient: class {
        constructor() {}
      },
    },
  }
})

const SESSION = {
  token: 'mock-token',
  user: { username: 'admin', name: '管理员', role: 'admin' },
}

let wrapper: VueWrapper | null = null
let consoleErrors: string[] = []

function spyConsole(): void {
  consoleErrors = []
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    consoleErrors.push(args.map(String).join(' '))
  })
}

async function mountAt(path: string): Promise<VueWrapper> {
  const pinia = createPinia()
  // 先挂载再导航：main.ts 里 pinia 先于 router 安装，路由守卫才能拿到 store
  wrapper = mount(App, {
    global: {
      plugins: [pinia, router],
    },
    attachTo: document.body,
  })
  await router.push(path)
  await router.isReady()
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('petdog_token', SESSION.token)
  localStorage.setItem('petdog_user', JSON.stringify(SESSION.user))
  spyConsole()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  const broken = consoleErrors.filter(
    (line) => line.includes('Failed to resolve component') || line.includes('Invalid prop'),
  )
  expect(broken).toEqual([])
})

describe('页面冒烟', () => {
  it('未登录访问 /devices 会回到登录页', async () => {
    localStorage.clear()
    const view = await mountAt('/devices')
    expect(view.text()).toContain('登录')
    expect(view.text()).toContain('STM32 智能桌面宠物')
  })

  it('设备页列出 mock 设备', async () => {
    const view = await mountAt('/devices')
    expect(view.text()).toContain('我的设备')
    expect(view.text()).toContain('桌宠一号')
    expect(view.text()).toContain('进入控制台')
  })

  it('控制台铺出 19 个动作按钮和 7 张表情', async () => {
    const view = await mountAt('/console')
    expect(view.text()).toContain('动作指令')
    expect(view.text()).toContain('音乐播放器')
    expect(view.findAll('.action-btn')).toHaveLength(19)
    expect(view.findAll('.face-btn')).toHaveLength(7)
  })

  it('点动作按钮先变黄、收到 ack 后变绿', async () => {
    const view = await mountAt('/console')
    const button = view.findAll('.action-btn')[0]
    await button.trigger('click')
    await flushPromises()
    expect(button.classes()).toContain('pending')

    await new Promise((resolve) => setTimeout(resolve, 1500))
    await flushPromises()
    expect(button.classes()).toContain('ok')
  })

  it('日志页显示表格与分页', async () => {
    const view = await mountAt('/logs')
    expect(view.text()).toContain('指令日志')
    expect(view.text()).toContain('应答结果')
    expect(view.findAll('.el-table__row').length).toBeGreaterThan(0)
  })

  it('看板渲染三张图与统计卡', async () => {
    const view = await mountAt('/dashboard')
    expect(view.text()).toContain('数据看板')
    expect(view.text()).toContain('电量曲线')
    expect(view.text()).toContain('指令成功率')
    expect(view.text()).toContain('动作分布')
    expect(view.findAll('.chart')).toHaveLength(3)
  })

  it('表情库有 7 张内置表情', async () => {
    const view = await mountAt('/faces')
    expect(view.text()).toContain('内置表情')
    expect(view.findAll('.face-card').length).toBeGreaterThanOrEqual(7)
  })

  it('场景页能加载列表和编辑器', async () => {
    const view = await mountAt('/scenes')
    expect(view.text()).toContain('场景编排')
    expect(view.text()).toContain('早上好')
    expect(view.text()).toContain('步骤编辑器')
  })
})
