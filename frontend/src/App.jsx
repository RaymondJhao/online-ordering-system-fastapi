import { Route, Routes } from 'react-router-dom'
import CustomerMenu from './pages/CustomerMenu'

function App() {
  return (
    <Routes>
      <Route path="/" element={<CustomerMenu />} />
    </Routes>
  )
}

export default App
