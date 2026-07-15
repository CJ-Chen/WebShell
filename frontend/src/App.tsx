import {
  Alert,
  App as AntApp,
  Avatar,
  Button,
  Dropdown,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Layout,
  Menu,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd'
import type { MenuProps, TableColumnsType, UploadProps } from 'antd'
import {
  Activity,
  ArrowLeft,
  CircleUserRound,
  File,
  FileText,
  Folder,
  FolderOpen,
  Gauge,
  Home,
  KeyRound,
  LockKeyhole,
  LogOut,
  Menu as MenuIcon,
  MoreHorizontal,
  Network,
  Pencil,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  Terminal as TerminalIcon,
  Trash2,
  UploadCloud,
  Users,
  X,
} from 'lucide-react'
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { FitAddon } from '@xterm/addon-fit'
import { Terminal } from '@xterm/xterm'
import { api, ApiError, setCsrfToken, terminalWebSocketUrl } from './api'
import type {
  AuditLog,
  AuthPayload,
  DestinationRule,
  FileItem,
  FileList,
  Target,
  TerminalSession,
  User,
} from './types'

const { Header, Sider, Content } = Layout
const { Text, Title } = Typography

interface AuthContextValue {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('Auth context missing')
  return value
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '操作失败'
}

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const payload = await api<AuthPayload>('/auth/me')
      setCsrfToken(payload.csrf_token)
      setUser(payload.user)
    } catch {
      setCsrfToken('')
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = async (username: string, password: string) => {
    const payload = await api<AuthPayload>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    setCsrfToken(payload.csrf_token)
    setUser(payload.user)
  }

  const logout = async () => {
    try {
      await api('/auth/logout', { method: 'POST' })
    } finally {
      setCsrfToken('')
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  )
}

function LoginPage() {
  const { login } = useAuth()
  const { message } = AntApp.useApp()
  const [submitting, setSubmitting] = useState(false)

  const submit = async (values: { username: string; password: string }) => {
    setSubmitting(true)
    try {
      await login(values.username, values.password)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel" aria-label="登录">
        <div className="brand-lockup login-brand">
          <div className="brand-mark"><TerminalIcon size={22} /></div>
          <div>
            <strong>WebShell</strong>
            <span>远程计算工作台</span>
          </div>
        </div>
        <Title level={2}>登录</Title>
        <Form layout="vertical" size="large" onFinish={submit} requiredMark={false}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input autoComplete="username" prefix={<CircleUserRound size={17} />} />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password autoComplete="current-password" prefix={<KeyRound size={17} />} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>进入工作台</Button>
        </Form>
      </section>
    </main>
  )
}

function ChangePasswordModal() {
  const { user, refresh } = useAuth()
  const { message } = AntApp.useApp()
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()

  const submit = async () => {
    const values = await form.validateFields()
    setLoading(true)
    try {
      await api('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: values.currentPassword,
          new_password: values.newPassword,
        }),
      })
      message.success('密码已更新')
      await refresh()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      title="设置新密码"
      open={Boolean(user?.must_change_password)}
      closable={false}
      maskClosable={false}
      keyboard={false}
      okText="更新密码"
      confirmLoading={loading}
      onOk={() => void submit()}
      cancelButtonProps={{ style: { display: 'none' } }}
    >
      <Form form={form} layout="vertical" requiredMark={false}>
        <Form.Item name="currentPassword" label="当前临时密码" rules={[{ required: true }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item name="newPassword" label="新密码" rules={[{ required: true }, { min: 6, message: '至少 6 个字符' }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirmPassword"
          label="确认新密码"
          dependencies={['newPassword']}
          rules={[
            { required: true },
            ({ getFieldValue }) => ({
              validator(_, value) {
                return !value || getFieldValue('newPassword') === value
                  ? Promise.resolve()
                  : Promise.reject(new Error('两次输入的密码不一致'))
              },
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  )
}

const navItems = [
  { key: '/workspace', icon: <TerminalIcon size={18} />, label: '工作区' },
  { key: '/targets', icon: <Server size={18} />, label: '目标机' },
]

function AppLayout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const items = user?.role === 'admin'
    ? [...navItems, { key: '/admin', icon: <ShieldCheck size={18} />, label: '管理' }]
    : navItems

  const userMenu: MenuProps['items'] = [
    { key: 'email', label: user?.email, disabled: true },
    { type: 'divider' },
    { key: 'logout', icon: <LogOut size={16} />, label: '退出登录', onClick: () => void logout() },
  ]

  return (
    <Layout className="app-layout">
      <Sider width={216} collapsedWidth={64} collapsed={collapsed} className="app-sider" trigger={null}>
        <div className={`brand-lockup sider-brand ${collapsed ? 'collapsed' : ''}`}>
          <div className="brand-mark"><TerminalIcon size={20} /></div>
          {!collapsed && <div><strong>WebShell</strong><span>SSH Relay</span></div>}
        </div>
        <Menu
          mode="inline"
          theme="dark"
          selectedKeys={[location.pathname]}
          items={items}
          onClick={({ key }) => navigate(key)}
        />
        <Tooltip title={collapsed ? '展开导航' : '收起导航'} placement="right">
          <Button
            type="text"
            className="sider-collapse"
            icon={collapsed ? <MenuIcon size={18} /> : <ArrowLeft size={18} />}
            onClick={() => setCollapsed((value) => !value)}
          />
        </Tooltip>
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="page-identity">
            <Button className="mobile-menu" type="text" icon={<MenuIcon size={19} />} onClick={() => setMobileNavOpen(true)} />
            <strong>{items.find((item) => item.key === location.pathname)?.label || '工作台'}</strong>
          </div>
          <Dropdown menu={{ items: userMenu }} placement="bottomRight">
            <Button type="text" className="user-trigger">
              <Avatar size={28}>{user?.username.slice(0, 1).toUpperCase()}</Avatar>
              <span>{user?.username}</span>
            </Button>
          </Dropdown>
        </Header>
        <Content className="app-content">
          <Routes>
            <Route path="/workspace" element={<WorkspacePage />} />
            <Route path="/targets" element={<TargetsPage />} />
            <Route path="/admin" element={user?.role === 'admin' ? <AdminPage /> : <Navigate to="/workspace" />} />
            <Route path="*" element={<Navigate to="/workspace" replace />} />
          </Routes>
        </Content>
      </Layout>
      <Drawer
        placement="left"
        width={216}
        open={mobileNavOpen}
        closable={false}
        onClose={() => setMobileNavOpen(false)}
        styles={{ body: { padding: 0, background: '#18201f' } }}
      >
        <div className="brand-lockup sider-brand">
          <div className="brand-mark"><TerminalIcon size={20} /></div>
          <div><strong>WebShell</strong><span>SSH Relay</span></div>
        </div>
        <Menu
          className="mobile-nav-menu"
          mode="inline"
          theme="dark"
          selectedKeys={[location.pathname]}
          items={items}
          onClick={({ key }) => { navigate(key); setMobileNavOpen(false) }}
        />
      </Drawer>
      <ChangePasswordModal />
    </Layout>
  )
}

function useTargets() {
  const [targets, setTargets] = useState<Target[]>([])
  const [loading, setLoading] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    try {
      setTargets(await api<Target[]>('/targets'))
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => { void load() }, [load])
  return { targets, loading, load }
}

function TargetStatus({ target }: { target: Target }) {
  if (target.status === 'connected') return <Tag color="success">已验证</Tag>
  if (target.status === 'error') return <Tag color="error">连接错误</Tag>
  return <Tag color="warning">待验证</Tag>
}

function TargetsPage() {
  const { targets, loading, load } = useTargets()
  const { message, modal } = AntApp.useApp()
  const [open, setOpen] = useState(false)
  const [unlockTarget, setUnlockTarget] = useState<Target | null>(null)
  const [editTarget, setEditTarget] = useState<Target | null>(null)
  const [saving, setSaving] = useState(false)
  const [form] = Form.useForm()
  const [unlockForm] = Form.useForm()
  const [editForm] = Form.useForm()
  const authMethod = Form.useWatch('auth_method', form)

  const probe = async (target: Target) => {
    try {
      const result = await api<{ fingerprint: string; algorithm: string; confirmed: boolean }>(
        `/targets/${target.id}/probe`,
        { method: 'POST' },
      )
      if (!result.confirmed) {
        modal.confirm({
          title: '确认服务器主机指纹',
          width: 560,
          content: (
            <div className="fingerprint-block">
              <Text type="secondary">{result.algorithm}</Text>
              <code>{result.fingerprint}</code>
            </div>
          ),
          okText: '指纹一致，确认',
          cancelText: '取消',
          onOk: async () => {
            await api(`/targets/${target.id}/confirm-host-key`, {
              method: 'POST',
              body: JSON.stringify(result),
            })
            message.success('主机指纹已确认')
            await load()
          },
        })
      } else {
        message.success('连接正常')
        await load()
      }
    } catch (error) {
      message.error(errorMessage(error))
      await load()
    }
  }

  const create = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const target = await api<Target>('/targets', {
        method: 'POST',
        body: JSON.stringify(values),
      })
      setOpen(false)
      form.resetFields()
      await load()
      await probe(target)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const unlock = async () => {
    if (!unlockTarget) return
    const values = await unlockForm.validateFields()
    setSaving(true)
    try {
      await api(`/targets/${unlockTarget.id}/unlock`, {
        method: 'POST',
        body: JSON.stringify({ secret: values.secret, save_secret: values.save_secret || false }),
      })
      setUnlockTarget(null)
      unlockForm.resetFields()
      message.success('凭据已更新')
      await probe(unlockTarget)
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const remove = async (target: Target) => {
    try {
      await api(`/targets/${target.id}`, { method: 'DELETE' })
      message.success('目标机已删除')
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    }
  }

  const saveEdit = async () => {
    if (!editTarget) return
    const values = await editForm.validateFields()
    setSaving(true)
    try {
      await api(`/targets/${editTarget.id}`, { method: 'PATCH', body: JSON.stringify(values) })
      setEditTarget(null)
      message.success('目标机配置已更新')
      await load()
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  const columns: TableColumnsType<Target> = [
    {
      title: '目标机',
      dataIndex: 'name',
      render: (_, target) => (
        <div className="primary-cell"><Server size={17} /><div><strong>{target.name}</strong><span>{target.username}@{target.host}:{target.port}</span></div></div>
      ),
    },
    { title: '认证', dataIndex: 'auth_method', width: 120, render: (value) => value === 'private_key' ? 'SSH 密钥' : '密码' },
    { title: '状态', width: 110, render: (_, target) => <TargetStatus target={target} /> },
    { title: '最近连接', dataIndex: 'last_connected_at', width: 170, render: (value) => value ? new Date(value).toLocaleString() : '—' },
    {
      title: '', width: 150, align: 'right',
      render: (_, target) => (
        <Space size={4}>
          <Tooltip title="测试连接"><Button type="text" icon={<Activity size={17} />} onClick={() => void probe(target)} /></Tooltip>
          <Tooltip title="编辑"><Button type="text" icon={<Pencil size={17} />} onClick={() => { setEditTarget(target); editForm.setFieldsValue(target) }} /></Tooltip>
          <Tooltip title="更新凭据"><Button type="text" icon={<KeyRound size={17} />} onClick={() => setUnlockTarget(target)} /></Tooltip>
          <Popconfirm title="删除此目标机？" description="终端记录也会删除。" onConfirm={() => void remove(target)}>
            <Tooltip title="删除"><Button type="text" danger icon={<Trash2 size={17} />} /></Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <section className="page-section">
      <div className="section-toolbar">
        <div><Title level={3}>目标服务器</Title><Text type="secondary">{targets.length} 个连接配置</Text></div>
        <Button type="primary" icon={<Plus size={17} />} onClick={() => setOpen(true)}>添加目标机</Button>
      </div>
      <div className="table-surface">
        <Table rowKey="id" columns={columns} dataSource={targets} loading={loading} pagination={false} scroll={{ x: 760 }} />
      </div>

      <Modal title="添加目标机" open={open} onCancel={() => setOpen(false)} onOk={() => void create()} confirmLoading={saving} okText="保存并测试">
        <Form form={form} layout="vertical" initialValues={{ port: 22, auth_method: 'password', save_secret: false }} requiredMark={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="计算节点 A" /></Form.Item>
          <div className="form-grid">
            <Form.Item name="host" label="IP 或域名" rules={[{ required: true }]}><Input placeholder="10.10.0.21" /></Form.Item>
            <Form.Item name="port" label="SSH 端口" rules={[{ required: true }]}><InputNumber min={1} max={65535} className="full-width" /></Form.Item>
          </div>
          <Form.Item name="username" label="Linux 用户名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="auth_method" label="认证方式"><Select options={[{ value: 'password', label: '用户名 + 密码' }, { value: 'private_key', label: 'SSH 私钥' }]} /></Form.Item>
          <Form.Item name="secret" label={authMethod === 'password' ? 'SSH 密码' : 'SSH 私钥'} rules={[{ required: true }]}>
            {authMethod === 'password' ? <Input.Password /> : <Input.TextArea rows={6} className="mono-input" />}
          </Form.Item>
          {authMethod === 'password' && <Form.Item name="save_secret" label="密码保存"><Select options={[{ value: false, label: '仅当前会话' }, { value: true, label: '加密保存' }]} /></Form.Item>}
          <Form.Item name="default_path" label="默认目录"><Input placeholder="留空使用远端 Home" /></Form.Item>
        </Form>
      </Modal>

      <Modal title={`更新凭据 · ${unlockTarget?.name || ''}`} open={Boolean(unlockTarget)} onCancel={() => setUnlockTarget(null)} onOk={() => void unlock()} confirmLoading={saving}>
        <Form form={unlockForm} layout="vertical" requiredMark={false}>
          <Form.Item name="secret" label={unlockTarget?.auth_method === 'password' ? 'SSH 密码' : 'SSH 私钥'} rules={[{ required: true }]}>
            {unlockTarget?.auth_method === 'password' ? <Input.Password /> : <Input.TextArea rows={7} className="mono-input" />}
          </Form.Item>
          {unlockTarget?.auth_method === 'password' && <Form.Item name="save_secret" label="保存方式" initialValue={false}><Select options={[{ value: false, label: '仅当前会话' }, { value: true, label: '加密保存' }]} /></Form.Item>}
        </Form>
      </Modal>
      <Modal title={`编辑目标机 · ${editTarget?.name || ''}`} open={Boolean(editTarget)} onCancel={() => setEditTarget(null)} onOk={() => void saveEdit()} confirmLoading={saving} okText="保存">
        <Form form={editForm} layout="vertical" requiredMark={false}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <div className="form-grid">
            <Form.Item name="host" label="IP 或域名" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="port" label="SSH 端口" rules={[{ required: true }]}><InputNumber min={1} max={65535} className="full-width" /></Form.Item>
          </div>
          <Form.Item name="username" label="Linux 用户名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="default_path" label="默认目录"><Input placeholder="留空使用远端 Home" /></Form.Item>
        </Form>
      </Modal>
    </section>
  )
}

function TerminalPane({ terminal }: { terminal: TerminalSession | null }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState('disconnected')

  useEffect(() => {
    if (!terminal || !containerRef.current) return
    const xterm = new Terminal({
      cursorBlink: true,
      convertEol: false,
      scrollback: 50_000,
      fontFamily: "'SFMono-Regular', Consolas, 'Liberation Mono', monospace",
      fontSize: 13,
      lineHeight: 1.25,
      theme: { background: '#101514', foreground: '#dbe5e1', cursor: '#57c5b6', selectionBackground: '#315c57' },
    })
    const fit = new FitAddon()
    xterm.loadAddon(fit)
    xterm.open(containerRef.current)
    fit.fit()
    const socket = new WebSocket(terminalWebSocketUrl(terminal.id, xterm.cols, xterm.rows))
    socket.binaryType = 'arraybuffer'
    let lastCols = 0
    let lastRows = 0
    const sendSize = (force = false) => {
      if (!containerRef.current || containerRef.current.clientWidth === 0 || containerRef.current.clientHeight === 0) return
      fit.fit()
      if (
        socket.readyState === WebSocket.OPEN
        && (force || xterm.cols !== lastCols || xterm.rows !== lastRows)
      ) {
        socket.send(JSON.stringify({ type: 'resize', cols: xterm.cols, rows: xterm.rows }))
        lastCols = xterm.cols
        lastRows = xterm.rows
      }
    }
    socket.onopen = () => {
      setStatus('connecting')
      requestAnimationFrame(() => sendSize(true))
    }
    socket.onmessage = (event) => {
      if (typeof event.data === 'string') {
        try {
          const payload = JSON.parse(event.data)
          if (payload.type === 'status') {
            setStatus(payload.status)
            if (payload.status === 'connected') requestAnimationFrame(() => sendSize(true))
          }
          if (payload.type === 'error') xterm.writeln(`\r\n[${payload.message}]`)
        } catch {
          xterm.write(event.data)
        }
      } else {
        xterm.write(new Uint8Array(event.data))
      }
    }
    socket.onclose = () => setStatus('disconnected')
    const input = xterm.onData((data) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'input', data }))
    })
    const observer = new ResizeObserver(() => sendSize())
    observer.observe(containerRef.current)
    return () => {
      observer.disconnect()
      input.dispose()
      socket.close()
      xterm.dispose()
    }
  }, [terminal])

  if (!terminal) return <div className="workspace-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择或创建终端" /></div>
  return (
    <div className="terminal-pane">
      <div className="terminal-toolbar">
        <div><TerminalIcon size={15} /><strong>{terminal.name}</strong><Tag color={terminal.persistence_mode === 'tmux' ? 'success' : 'warning'}>{terminal.persistence_mode}</Tag></div>
        <span className={`connection-state ${status}`}><i />{status === 'connected' ? '已连接' : status === 'connecting' ? '连接中' : '已断开'}</span>
      </div>
      {terminal.persistence_mode === 'shell' && <Alert banner type="warning" showIcon message="目标机未安装 tmux，断开后任务可能结束" />}
      <div ref={containerRef} className="xterm-host" />
    </div>
  )
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let amount = value / 1024
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1 }
  return `${amount.toFixed(amount >= 10 ? 1 : 2)} ${units[unit]}`
}

function FileManager({ target }: { target: Target | null }) {
  const { message, modal } = AntApp.useApp()
  const [listing, setListing] = useState<FileList | null>(null)
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<{ name: string; content: string; truncated: boolean; mimeType: string; encoding: 'text' | 'base64' } | null>(null)

  const load = useCallback(async (path?: string) => {
    if (!target) { setListing(null); return }
    setLoading(true)
    try {
      const query = new URLSearchParams({ target_id: target.id, path: path || target.default_path || '.' })
      setListing(await api<FileList>(`/files?${query}`))
    } catch (error) {
      message.error(errorMessage(error))
    } finally {
      setLoading(false)
    }
  }, [message, target])

  useEffect(() => { void load() }, [load])

  const openItem = async (item: FileItem) => {
    if (item.type === 'directory') { await load(item.path); return }
    try {
      const query = new URLSearchParams({ target_id: target!.id, path: item.path })
      const result = await api<{ content: string; truncated: boolean; mime_type: string; encoding: 'text' | 'base64' }>(`/files/preview?${query}`)
      setPreview({ name: item.name, content: result.content, truncated: result.truncated, mimeType: result.mime_type, encoding: result.encoding })
    } catch (error) {
      if (error instanceof ApiError && error.status === 415) {
        download(item)
      } else message.error(errorMessage(error))
    }
  }

  const download = (item: FileItem) => {
    const query = new URLSearchParams({ target_id: target!.id, path: item.path })
    const anchor = document.createElement('a')
    anchor.href = `/api/v1/files/download?${query}`
    anchor.click()
  }

  const createDirectory = () => {
    let value = ''
    modal.confirm({
      title: '新建目录',
      content: <Input autoFocus placeholder="目录名" onChange={(event) => { value = event.target.value }} />,
      okText: '创建',
      onOk: async () => {
        if (!value.trim()) throw new Error('请输入目录名')
        await api(`/files/mkdir?target_id=${encodeURIComponent(target!.id)}`, {
          method: 'POST',
          body: JSON.stringify({ path: `${listing!.path}/${value.trim()}` }),
        })
        await load(listing!.path)
      },
    })
  }

  const remove = async (item: FileItem) => {
    try {
      await api(`/files/delete?target_id=${encodeURIComponent(target!.id)}`, {
        method: 'POST',
        body: JSON.stringify({ path: item.path, recursive: item.type === 'directory' }),
      })
      message.success('已删除')
      await load(listing!.path)
    } catch (error) { message.error(errorMessage(error)) }
  }

  const rename = (item: FileItem) => {
    let value = item.name
    modal.confirm({
      title: '重命名',
      content: <Input autoFocus defaultValue={item.name} onChange={(event) => { value = event.target.value }} />,
      okText: '保存',
      onOk: async () => {
        const destination = `${listing!.path}/${value.trim()}`
        await api(`/files/move?target_id=${encodeURIComponent(target!.id)}`, {
          method: 'POST',
          body: JSON.stringify({ source: item.path, destination }),
        })
        await load(listing!.path)
      },
    })
  }

  const uploadProps: UploadProps = {
    showUploadList: false,
    customRequest: async ({ file, onSuccess, onError }) => {
      const body = new FormData()
      body.append('target_id', target!.id)
      body.append('path', `${listing!.path}/${(file as File).name}`)
      body.append('upload', file as File)
      try {
        await api('/files/upload', { method: 'POST', body })
        message.success('上传完成')
        onSuccess?.({})
        await load(listing!.path)
      } catch (error) {
        message.error(errorMessage(error)); onError?.(error as Error)
      }
    },
  }

  if (!target) return <div className="workspace-empty"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择目标机后浏览文件" /></div>

  const columns: TableColumnsType<FileItem> = [
    {
      title: '名称', dataIndex: 'name', ellipsis: true,
      render: (_, item) => <button className="file-name" onDoubleClick={() => void openItem(item)} onClick={() => item.type === 'directory' && void openItem(item)}>{item.type === 'directory' ? <Folder size={16} /> : <File size={16} />}<span>{item.name}</span></button>,
    },
    { title: '大小', dataIndex: 'size', width: 88, render: (value, item) => item.type === 'directory' ? '—' : formatBytes(value) },
    {
      title: '', width: 42,
      render: (_, item) => (
        <Dropdown menu={{ items: [
          { key: 'open', icon: <FileText size={15} />, label: '打开', onClick: () => void openItem(item) },
          { key: 'rename', icon: <Pencil size={15} />, label: '重命名', onClick: () => rename(item) },
          ...(item.type === 'file' ? [{ key: 'download', icon: <FolderOpen size={15} />, label: '下载', onClick: () => download(item) }] : []),
          { type: 'divider' as const },
          { key: 'delete', danger: true, icon: <Trash2 size={15} />, label: '删除', onClick: () => modal.confirm({ title: `删除 ${item.name}？`, okType: 'danger', onOk: () => remove(item) }) },
        ] }} trigger={['click']}>
          <Button type="text" size="small" icon={<MoreHorizontal size={16} />} />
        </Dropdown>
      ),
    },
  ]

  return (
    <div className="file-manager">
      <div className="file-toolbar">
        <Tooltip title="上一级"><Button type="text" icon={<ArrowLeft size={16} />} disabled={!listing || listing.path === '/'} onClick={() => void load(listing ? listing.path.replace(/\/?[^/]+$/, '') || '/' : '.')} /></Tooltip>
        <Tooltip title="Home"><Button type="text" icon={<Home size={16} />} onClick={() => listing && void load(listing.home_path)} /></Tooltip>
        <Tooltip title="刷新"><Button type="text" icon={<RefreshCw size={16} />} onClick={() => void load(listing?.path)} /></Tooltip>
        <div className="path-display" title={listing?.path}>{listing?.path || '连接中'}</div>
        <Tooltip title="新建目录"><Button type="text" icon={<FolderOpen size={16} />} disabled={!listing} onClick={createDirectory} /></Tooltip>
        <Upload {...uploadProps}><Tooltip title="上传"><Button type="text" icon={<UploadCloud size={16} />} disabled={!listing} /></Tooltip></Upload>
      </div>
      <Table rowKey="path" size="small" columns={columns} dataSource={listing?.items || []} loading={loading} pagination={false} scroll={{ y: 'calc(100vh - 190px)' }} />
      <Modal title={preview?.name} open={Boolean(preview)} footer={null} width={760} onCancel={() => setPreview(null)}>
        {preview?.truncated && <Alert type="warning" banner message="文件较大，仅显示前 2 MiB" />}
        {preview?.encoding === 'base64'
          ? <div className="image-preview"><img src={`data:${preview.mimeType};base64,${preview.content}`} alt={preview.name} /></div>
          : <pre className="file-preview">{preview?.content}</pre>}
      </Modal>
    </div>
  )
}

function WorkspacePage() {
  const { targets } = useTargets()
  const { message } = AntApp.useApp()
  const [terminals, setTerminals] = useState<TerminalSession[]>([])
  const [selectedTargetId, setSelectedTargetId] = useState<string>('')
  const [selectedTerminalId, setSelectedTerminalId] = useState<string>('')
  const [createOpen, setCreateOpen] = useState(false)
  const [mobileLayout, setMobileLayout] = useState(() => window.matchMedia('(max-width: 760px)').matches)
  const [form] = Form.useForm()

  const loadTerminals = useCallback(async () => {
    try { setTerminals(await api<TerminalSession[]>('/terminals')) }
    catch (error) { message.error(errorMessage(error)) }
  }, [message])

  useEffect(() => { void loadTerminals() }, [loadTerminals])
  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)')
    const updateLayout = (event: MediaQueryListEvent) => setMobileLayout(event.matches)
    media.addEventListener('change', updateLayout)
    return () => media.removeEventListener('change', updateLayout)
  }, [])
  useEffect(() => {
    if (!selectedTargetId && targets.length) setSelectedTargetId(targets[0].id)
  }, [selectedTargetId, targets])

  const selectedTarget = targets.find((item) => item.id === selectedTargetId) || null
  const targetTerminals = terminals.filter((item) => item.target_id === selectedTargetId)
  const selectedTerminal = terminals.find((item) => item.id === selectedTerminalId) || null

  const createTerminal = async () => {
    const values = await form.validateFields()
    try {
      const terminal = await api<TerminalSession>('/terminals', {
        method: 'POST', body: JSON.stringify({ target_id: selectedTargetId, name: values.name }),
      })
      setCreateOpen(false); form.resetFields(); await loadTerminals(); setSelectedTerminalId(terminal.id)
    } catch (error) { message.error(errorMessage(error)) }
  }

  const deleteTerminal = async (terminal: TerminalSession) => {
    try {
      await api(`/terminals/${terminal.id}`, { method: 'DELETE' })
      if (selectedTerminalId === terminal.id) setSelectedTerminalId('')
      await loadTerminals()
    } catch (error) { message.error(errorMessage(error)) }
  }

  const terminalList = (
    <aside className="terminal-list">
      <div className="target-select-wrap">
        <Select
          value={selectedTargetId || undefined}
          placeholder="选择目标机"
          onChange={(value) => { setSelectedTargetId(value); setSelectedTerminalId('') }}
          options={targets.map((target) => ({ value: target.id, label: target.name }))}
          suffixIcon={<Server size={15} />}
        />
      </div>
      <div className="panel-heading"><span>终端</span><Tooltip title="新建终端"><Button type="text" size="small" icon={<Plus size={16} />} disabled={!selectedTarget} onClick={() => setCreateOpen(true)} /></Tooltip></div>
      <div className="terminal-items">
        {targetTerminals.map((terminal) => (
          <button key={terminal.id} className={`terminal-item ${selectedTerminalId === terminal.id ? 'active' : ''}`} onClick={() => setSelectedTerminalId(terminal.id)}>
            <TerminalIcon size={15} /><span>{terminal.name}</span><Tag>{terminal.persistence_mode}</Tag>
            <Popconfirm title="删除终端？" onConfirm={() => void deleteTerminal(terminal)}>
              <span className="terminal-delete" onClick={(event) => event.stopPropagation()}><X size={14} /></span>
            </Popconfirm>
          </button>
        ))}
        {!targetTerminals.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无终端" />}
      </div>
    </aside>
  )

  if (!targets.length) {
    return <div className="workspace-empty full-page"><Empty description="尚未配置目标服务器"><Button type="primary" href="/targets">添加目标机</Button></Empty></div>
  }

  return (
    <section className="workspace-page">
      {mobileLayout ? (
        <div className="workspace-mobile">
          {terminalList}
          <Tabs items={[
            { key: 'terminal', label: '终端', children: <TerminalPane terminal={selectedTerminal} /> },
            { key: 'files', label: '文件', children: <FileManager target={selectedTarget} /> },
          ]} />
        </div>
      ) : (
        <div className="workspace-desktop">
          {terminalList}
          <TerminalPane terminal={selectedTerminal} />
          <FileManager target={selectedTarget} />
        </div>
      )}
      <Modal title="新建终端" open={createOpen} onCancel={() => setCreateOpen(false)} onOk={() => void createTerminal()} okText="创建">
        <Form form={form} layout="vertical" initialValues={{ name: `Terminal ${targetTerminals.length + 1}` }}>
          <Form.Item name="name" label="终端名称" rules={[{ required: true }]}><Input /></Form.Item>
        </Form>
      </Modal>
    </section>
  )
}

function AdminPage() {
  const { message, modal } = AntApp.useApp()
  const [users, setUsers] = useState<User[]>([])
  const [rules, setRules] = useState<DestinationRule[]>([])
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [userOpen, setUserOpen] = useState(false)
  const [ruleOpen, setRuleOpen] = useState(false)
  const [userForm] = Form.useForm()
  const [ruleForm] = Form.useForm()

  const load = useCallback(async () => {
    try {
      const [userData, ruleData, logData] = await Promise.all([
        api<User[]>('/admin/users'), api<DestinationRule[]>('/admin/destination-rules'), api<AuditLog[]>('/admin/audit-logs?limit=100'),
      ])
      setUsers(userData); setRules(ruleData); setLogs(logData)
    } catch (error) { message.error(errorMessage(error)) }
  }, [message])
  useEffect(() => { void load() }, [load])

  const createUser = async () => {
    const values = await userForm.validateFields()
    try {
      const result = await api<{ user: User; temporary_password: string | null }>('/admin/users', { method: 'POST', body: JSON.stringify(values) })
      setUserOpen(false); userForm.resetFields(); await load()
      if (result.temporary_password) modal.info({ title: '临时密码', content: <code className="temporary-password">{result.temporary_password}</code>, okText: '已记录' })
    } catch (error) { message.error(errorMessage(error)) }
  }

  const userAction = async (user: User, action: string) => {
    try {
      const result = await api<{ temporary_password?: string }>(`/admin/users/${user.id}/${action}`, { method: 'POST' })
      if (result.temporary_password) modal.info({ title: `${user.username} 的临时密码`, content: <code className="temporary-password">{result.temporary_password}</code>, okText: '已记录' })
      await load()
    } catch (error) { message.error(errorMessage(error)) }
  }

  const createRule = async () => {
    const values = await ruleForm.validateFields()
    try {
      await api('/admin/destination-rules', { method: 'POST', body: JSON.stringify(values) })
      setRuleOpen(false); ruleForm.resetFields(); await load()
    } catch (error) { message.error(errorMessage(error)) }
  }

  const userColumns: TableColumnsType<User> = [
    { title: '用户', render: (_, user) => <div className="primary-cell"><Avatar size={30}>{user.username[0].toUpperCase()}</Avatar><div><strong>{user.username}</strong><span>{user.email}</span></div></div> },
    { title: '角色', dataIndex: 'role', width: 90, render: (role) => role === 'admin' ? '管理员' : '用户' },
    { title: '状态', dataIndex: 'status', width: 100, render: (status) => <Tag color={status === 'active' ? 'success' : 'default'}>{status}</Tag> },
    { title: '最近登录', dataIndex: 'last_login_at', width: 170, render: (value) => value ? new Date(value).toLocaleString() : '—' },
    {
      title: '', width: 180, align: 'right', render: (_, user) => (
        <Space size={4}>
          <Tooltip title="重置密码"><Button type="text" icon={<KeyRound size={16} />} onClick={() => modal.confirm({ title: `重置 ${user.username} 的密码？`, onOk: () => userAction(user, 'reset-password') })} /></Tooltip>
          {user.status === 'active'
            ? <Tooltip title="停用"><Button type="text" icon={<LockKeyhole size={16} />} onClick={() => void userAction(user, 'disable')} /></Tooltip>
            : <Tooltip title="启用"><Button type="text" icon={<ShieldCheck size={16} />} onClick={() => void userAction(user, 'enable')} /></Tooltip>}
          <Tooltip title="归档"><Button type="text" danger icon={<Trash2 size={16} />} onClick={() => modal.confirm({ title: `归档 ${user.username}？`, okType: 'danger', onOk: () => userAction(user, 'archive') })} /></Tooltip>
          {user.status === 'archived' && <Tooltip title="永久删除"><Button type="text" danger icon={<X size={16} />} onClick={() => modal.confirm({ title: `永久删除 ${user.username}？`, content: '只删除面板账号、连接配置和加密凭据，不修改远端服务器数据。', okType: 'danger', okText: '永久删除', onOk: async () => { await api(`/admin/users/${user.id}`, { method: 'DELETE' }); await load() } })} /></Tooltip>}
        </Space>
      ),
    },
  ]

  const ruleColumns: TableColumnsType<DestinationRule> = [
    { title: '类型', dataIndex: 'kind', width: 100, render: (value) => value === 'cidr' ? 'CIDR' : '域名' },
    { title: '地址规则', dataIndex: 'value' },
    { title: '端口', width: 110, render: (_, rule) => rule.port_min === rule.port_max ? rule.port_min : `${rule.port_min}-${rule.port_max}` },
    { title: '说明', dataIndex: 'description', render: (value) => value || '—' },
    { title: '', width: 60, render: (_, rule) => <Popconfirm title="删除规则？" onConfirm={async () => { await api(`/admin/destination-rules/${rule.id}`, { method: 'DELETE' }); await load() }}><Button type="text" danger icon={<Trash2 size={16} />} /></Popconfirm> },
  ]

  const logColumns: TableColumnsType<AuditLog> = [
    { title: '时间', dataIndex: 'created_at', width: 180, render: (value) => new Date(value).toLocaleString() },
    { title: '操作', dataIndex: 'action', width: 220 },
    { title: '结果', dataIndex: 'outcome', width: 90, render: (value) => <Tag color={value === 'success' ? 'success' : 'error'}>{value}</Tag> },
    { title: '资源', render: (_, log) => `${log.resource_type}${log.resource_id ? ` · ${log.resource_id}` : ''}` },
    { title: '来源 IP', dataIndex: 'ip_address', width: 140, render: (value) => value || '—' },
  ]

  return (
    <section className="page-section">
      <Tabs items={[
        { key: 'users', label: <span className="tab-label"><Users size={16} />用户</span>, children: <><div className="section-toolbar compact"><div><Title level={3}>用户</Title><Text type="secondary">{users.length} 个 Web 账号</Text></div><Button type="primary" icon={<Plus size={16} />} onClick={() => setUserOpen(true)}>创建用户</Button></div><div className="table-surface"><Table rowKey="id" columns={userColumns} dataSource={users} pagination={false} scroll={{ x: 760 }} /></div></> },
        { key: 'rules', label: <span className="tab-label"><Network size={16} />地址规则</span>, children: <><div className="section-toolbar compact"><div><Title level={3}>目标地址规则</Title><Text type="secondary">SSH 连接白名单</Text></div><Button type="primary" icon={<Plus size={16} />} onClick={() => setRuleOpen(true)}>添加规则</Button></div><div className="table-surface"><Table rowKey="id" columns={ruleColumns} dataSource={rules} pagination={false} /></div></> },
        { key: 'audit', label: <span className="tab-label"><Gauge size={16} />审计</span>, children: <><div className="section-toolbar compact"><div><Title level={3}>审计日志</Title><Text type="secondary">最近 100 条事件</Text></div><Button icon={<RefreshCw size={16} />} onClick={() => void load()}>刷新</Button></div><div className="table-surface"><Table rowKey="id" columns={logColumns} dataSource={logs} pagination={false} scroll={{ x: 900 }} /></div></> },
      ]} />

      <Modal title="创建用户" open={userOpen} onCancel={() => setUserOpen(false)} onOk={() => void createUser()} okText="创建">
        <Form form={userForm} layout="vertical" initialValues={{ role: 'user' }} requiredMark={false}>
          <Form.Item name="username" label="用户名" rules={[{ required: true }, { pattern: /^[a-z][a-z0-9_-]{2,31}$/, message: '使用 3-32 位小写字母、数字、_ 或 -' }]}><Input /></Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ required: true }, { type: 'email' }]}><Input /></Form.Item>
          <Form.Item name="role" label="角色"><Select options={[{ value: 'user', label: '用户' }, { value: 'admin', label: '管理员' }]} /></Form.Item>
          <Form.Item name="password" label="初始密码" rules={[{ min: 6, message: '至少 6 个字符' }]}><Input.Password placeholder="留空自动生成临时密码" /></Form.Item>
        </Form>
      </Modal>
      <Modal title="添加目标地址规则" open={ruleOpen} onCancel={() => setRuleOpen(false)} onOk={() => void createRule()} okText="添加">
        <Form form={ruleForm} layout="vertical" initialValues={{ kind: 'cidr', port_min: 22, port_max: 22, enabled: true }} requiredMark={false}>
          <Form.Item name="kind" label="类型"><Select options={[{ value: 'cidr', label: 'CIDR 网段' }, { value: 'domain', label: '域名后缀' }]} /></Form.Item>
          <Form.Item name="value" label="规则" rules={[{ required: true }]}><Input placeholder="10.20.0.0/16" /></Form.Item>
          <div className="form-grid"><Form.Item name="port_min" label="起始端口"><InputNumber min={1} max={65535} className="full-width" /></Form.Item><Form.Item name="port_max" label="结束端口"><InputNumber min={1} max={65535} className="full-width" /></Form.Item></div>
          <Form.Item name="description" label="说明"><Input /></Form.Item>
        </Form>
      </Modal>
    </section>
  )
}

function RootContent() {
  const { user, loading } = useAuth()
  if (loading) return <div className="app-loading"><Spin size="large" /></div>
  return user ? <AppLayout /> : <LoginPage />
}

export default function RootApp() {
  return <AuthProvider><RootContent /></AuthProvider>
}
