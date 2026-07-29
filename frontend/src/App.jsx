import { Route, Routes } from 'react-router-dom'
import CustomerMenu from './pages/CustomerMenu'
import Checkout from './pages/Checkout'
import CustomerOrders from './pages/CustomerOrders'
import Auth from './pages/Auth'
import MerchantDashboard from './pages/MerchantDashboard'
import BackendStatusBanner from './components/BackendStatusBanner'
import { CartProvider } from './context/CartContext'

function App() {
  return (
    <CartProvider>
      {/* 一進站就在背景喚醒後端（Render 免費方案閒置 15 分鐘會休眠），
          並在等待超過 2 秒時顯示提示 */}
      <BackendStatusBanner />
      <Routes>
        <Route path="/" element={<CustomerMenu />} />
        <Route path="/checkout" element={<Checkout />} />
        <Route path="/orders" element={<CustomerOrders />} />
        <Route path="/auth" element={<Auth />} />
        <Route path="/merchant" element={<MerchantDashboard />} />
      </Routes>
    </CartProvider>
  )
}

export default App
