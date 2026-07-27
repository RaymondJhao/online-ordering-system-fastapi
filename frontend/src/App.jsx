import { Route, Routes } from 'react-router-dom'
import CustomerMenu from './pages/CustomerMenu'
import Checkout from './pages/Checkout'
import { CartProvider } from './context/CartContext'

function App() {
  return (
    <CartProvider>
      <Routes>
        <Route path="/" element={<CustomerMenu />} />
        <Route path="/checkout" element={<Checkout />} />
      </Routes>
    </CartProvider>
  )
}

export default App
