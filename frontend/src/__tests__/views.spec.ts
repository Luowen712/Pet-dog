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
  user: { id: 1, username: 'admin', name: '管理员', role: 'admin' },
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
    expect(view.text()).toContain('登录控制台')
    expect(view.text()).toContain('PET-DOG')
  })

  it('登录页能切到注册表单', async () => {
    localStorage.clear()
    const view = await mountAt('/login')
    const link = view.findAll('.el-link').find((node) => node.text() === '注册')
    expect(link).toBeTruthy()
    await link!.trigger('click')
    await flushPromises()
    expect(view.text()).toContain('注册账号')
    expect(view.text()).toContain('确认密码')
    expect(view.text()).toContain('创建账号')
  })

  it('设备页列出 mock 设备，并支持不解绑直接打开重连蓝牙面板', async () => {
    const view = await mountAt('/devices')
    expect(view.text()).toContain('我的设备')
    expect(view.text()).toContain('桌宠一号')
    expect(view.text()).toContain('进入控制台')
    const reconnectBtn = view.findAll('button').find((b) => b.text().includes('重连蓝牙'))
    expect(reconnectBtn).toBeTruthy()
    await reconnectBtn!.trigger('click')
    await flushPromises()
    expect(view.text()).toContain('扫描并重连低功耗蓝牙')
    expect(view.text()).toContain('SIM-ECB02H2-01')
  })

  it('无绑定设备时展示低功耗蓝牙扫描与直连，无配对码输入框', async () => {
    const view = await mountAt('/devices')
    const { useDeviceStore } = await import('@/stores/device')
    const deviceStore = useDeviceStore()
    deviceStore.devices = []
    await deviceStore.scanBle()
    await flushPromises()
    expect(view.text()).toContain('BLE / ECB02H2')
    expect(view.text()).toContain('SIM-ECB02H2-01')
    expect(view.text()).not.toContain('输入 6 位配对码')
  })

  it('控制台铺出 19 个动作按钮，其中只有 7 个启用，7 张表情', async () => {
    const view = await mountAt('/console')
    expect(view.text()).toContain('动作指令')
    expect(view.findAll('.action-btn')).toHaveLength(19)
    // 等待 WS open 与本次 HTTP 基线；未完成同步前不许控制。
    await vi.waitFor(() => expect(view.findAll('.action-btn.disabled')).toHaveLength(12))
    expect(view.findAll('.action-btn:not(.disabled)')).toHaveLength(7)
    expect(view.findAll('.face-btn')).toHaveLength(7)
  })

  it('断开实时通道后不允许继续点击动作', async () => {
    const view = await mountAt('/console')
    const { usePetStore } = await import('@/stores/pet')
    usePetStore().disconnect()
    await flushPromises()
    expect(view.findAll('.action-btn:not(.disabled)')).toHaveLength(0)
    expect(view.text()).toContain('离线')
  })

  it('控制台仅展示设备在线状态，动作分组默认收起且支持点击展开与全部展开', async () => {
    const view = await mountAt('/console')
    await vi.waitFor(() => expect(view.text()).toContain('在线'))
    expect(view.text()).not.toContain('网页控制台')
    expect(view.text()).not.toContain('本地后端')

    // 5 个动作分组默认全部收纳
    expect(view.findAll('.drawer')).toHaveLength(5)
    expect(view.findAll('.drawer.open')).toHaveLength(0)

    // 点击第一个分组抽屉展开，再次点击收起
    const firstHead = view.findAll('.drawer-head')[0]
    await firstHead.trigger('click')
    expect(view.findAll('.drawer.open')).toHaveLength(1)
    await firstHead.trigger('click')
    expect(view.findAll('.drawer.open')).toHaveLength(0)

    // 支持一键全部展开/收起
    const toggleAll = view.find('.toggle-all')
    await toggleAll.trigger('click')
    expect(view.findAll('.drawer.open')).toHaveLength(5)
    await toggleAll.trigger('click')
    expect(view.findAll('.drawer.open')).toHaveLength(0)

    // 设备离线时展示离线与重连蓝牙入口
    const { usePetStore } = await import('@/stores/pet')
    const pet = usePetStore()
    pet.online = false
    pet.controlState = 'offline'
    await flushPromises()
    expect(view.text()).toContain('离线')
    expect(view.text()).toContain('重连蓝牙')
  })

  it('点动作先黄；完成后绿 1.5 秒，然后自动熄灭', async () => {
    const view = await mountAt('/console')
    await vi.waitFor(() => expect(view.findAll('.action-btn:not(.disabled)')).toHaveLength(7))
    const button = view.findAll('.action-btn:not(.disabled)')[0]
    await button.trigger('click')
    await flushPromises()
    expect(button.classes()).not.toContain('ok')
    expect(['pending', 'accepted']).toContain(
      button.classes().find((name) => ['pending', 'accepted'].includes(name)),
    )

    // mock 在 520–1140ms 推 done，此时按钮短暂变绿
    await new Promise((resolve) => setTimeout(resolve, 1400))
    await flushPromises()
    expect(button.classes()).toContain('ok')

    // 绿灯只停留 1.5 秒，之后自动回到 idle，不留常亮
    await new Promise((resolve) => setTimeout(resolve, 1600))
    await flushPromises()
    for (const state of ['pending', 'accepted', 'ok', 'fail', 'unknown']) {
      expect(button.classes()).not.toContain(state)
    }
  })

  it('日志、看板、场景的路由已隐藏，深链回到设备页', async () => {
    expect(router.hasRoute('logs')).toBe(false)
    expect(router.hasRoute('dashboard')).toBe(false)
    expect(router.hasRoute('scenes')).toBe(false)

    const view = await mountAt('/logs')
    expect(view.text()).toContain('我的设备')
    expect(view.text()).not.toContain('指令日志')
  })

  it('表情库有 7 张内置表情，没有上传入口，且仅从控制台入口进入', async () => {
    const view = await mountAt('/console')
    const navTexts = view.findAll('.nav-item').map((node) => node.text())
    expect(navTexts).toEqual(['设备', '控制台'])

    const enterLib = view.find('.face-lib-link')
    expect(enterLib.exists()).toBe(true)
    expect(enterLib.text()).toContain('进入表情库')

    await router.push('/faces')
    await flushPromises()
    await new Promise((resolve) => setTimeout(resolve, 60))
    await flushPromises()

    expect(view.text()).toContain('内置表情')
    expect(view.text()).toContain('返回控制台')
    const cards = view.findAll('.face-card')
    expect(cards.length).toBeGreaterThanOrEqual(7)
    expect(view.text()).not.toContain('上传表情')

    // 等待实时通道就绪后再下发表情
    await vi.waitFor(() => expect(view.text()).toContain('在线'))

    // 点击卡片可切换大屏预览，点击应用可下发表情（0..6 与固件 DebugUI.c 对齐）
    expect(cards.map((c) => c.find('.name').text())).toEqual([
      '睡觉',
      '委屈',
      '开心',
      '狂热',
      '超开心',
      '眼睛',
      '震惊',
    ])
    await cards[1].trigger('click')
    await flushPromises()
    expect(view.find('.preview-name').text()).toBe('委屈')

    const applyBtn = view.findAll('button').find((b) => b.text().includes('应用到桌宠'))
    expect(applyBtn).toBeTruthy()
    await applyBtn!.trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(view.text()).toContain('当前使用'))
  })

  it('账号页提供改密、全部退出和注销', async () => {
    const view = await mountAt('/account')
    expect(view.text()).toContain('修改密码')
    expect(view.text()).toContain('退出所有设备上的登录')
    expect(view.text()).toContain('注销账号')
  })
})
