import { Route, Routes } from 'react-router-dom'
import CustomerMenu from './pages/CustomerMenu'
import Checkout from './pages/Checkout'
import CustomerOrders from './pages/CustomerOrders'
import Auth from './pages/Auth'
import MerchantDashboard from './pages/MerchantDashboard'
import { CartProvider } from './context/CartContext'

function App() {
  return (
    <CartProvider>
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
