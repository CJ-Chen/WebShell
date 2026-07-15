import ReactDOM from 'react-dom/client'
import { App as AntApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { BrowserRouter } from 'react-router-dom'
import RootApp from './App'
import '@xterm/xterm/css/xterm.css'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <ConfigProvider
    locale={zhCN}
    theme={{
      token: {
        colorPrimary: '#087f73',
        colorInfo: '#087f73',
        colorWarning: '#b86b11',
        colorError: '#b84040',
        borderRadius: 6,
        fontFamily: "Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif",
      },
    }}
  >
    <AntApp>
      <BrowserRouter>
        <RootApp />
      </BrowserRouter>
    </AntApp>
  </ConfigProvider>,
)
