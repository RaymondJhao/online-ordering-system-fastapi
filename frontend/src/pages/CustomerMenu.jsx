import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { ShoppingCart, Plus, Minus, X, User } from 'lucide-react'
import { useCart } from '../context/CartContext'

function CustomerMenu() {
  const navigate = useNavigate()
  const { cart, addToCart, changeQuantity, totalCount, totalPrice } = useCart()
  const [menuItems, setMenuItems] = useState([])
  const [isCartOpen, setIsCartOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    axios
      .get('/api/menu')
      .then((res) => {
        const items = Array.isArray(res.data) ? res.data : res.data.items ?? []
        setMenuItems(items)
      })
      .catch(() => {
        setError('無法取得餐點資料，請稍後再試')
      })
      .finally(() => {
        setIsLoading(false)
      })
  }, [])

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="sticky top-0 z-30 bg-white shadow-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">
            美味點餐
          </h1>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => navigate('/auth')}
              className="flex items-center gap-2 rounded-full border border-gray-300 px-4 py-2 text-gray-600 hover:bg-gray-100 transition-colors"
            >
              <User size={20} />
              <span className="hidden sm:inline">登入 / 註冊</span>
            </button>
            <button
              type="button"
              onClick={() => setIsCartOpen(true)}
              className="relative flex items-center gap-2 rounded-full bg-orange-500 px-4 py-2 text-white shadow hover:bg-orange-600 transition-colors"
            >
              <ShoppingCart size={20} />
              <span className="hidden sm:inline">購物車</span>
              {totalCount > 0 && (
                <span className="absolute -top-2 -right-2 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-xs font-bold text-white">
                  {totalCount}
                </span>
              )}
            </button>
          </div>
        </div>
      </nav>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        {isLoading && (
          <p className="py-12 text-center text-gray-500">餐點載入中...</p>
        )}

        {error && <p className="py-12 text-center text-red-500">{error}</p>}

        {!isLoading && !error && menuItems.length === 0 && (
          <p className="py-12 text-center text-gray-500">目前沒有可供點選的餐點</p>
        )}

        {!isLoading && !error && menuItems.length > 0 && (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {menuItems.map((item) => (
              <div
                key={item.id}
                className="flex flex-col overflow-hidden rounded-2xl bg-white shadow-md transition-shadow hover:shadow-lg"
              >
                <div className="flex flex-1 flex-col p-5">
                  <h3 className="text-lg font-semibold text-gray-900">
                    {item.name}
                  </h3>
                  <p className="mt-1 flex-1 text-sm text-gray-500 line-clamp-2">
                    {item.description}
                  </p>
                  <div className="mt-4 flex items-center justify-between">
                    <span className="text-lg font-bold text-orange-500">
                      NT$ {item.price}
                    </span>
                    <button
                      type="button"
                      onClick={() => addToCart(item)}
                      className="rounded-full bg-orange-500 px-4 py-2 text-sm font-medium text-white shadow hover:bg-orange-600 transition-colors"
                    >
                      加入購物車
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {isCartOpen && (
        <div className="fixed inset-0 z-40 flex justify-end">
          <button
            type="button"
            aria-label="關閉購物車"
            onClick={() => setIsCartOpen(false)}
            className="absolute inset-0 bg-black/40"
          />
          <div className="relative flex h-full w-full max-w-sm flex-col bg-white shadow-xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <h2 className="text-lg font-bold text-gray-900">我的購物車</h2>
              <button
                type="button"
                onClick={() => setIsCartOpen(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={22} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              {cart.length === 0 ? (
                <p className="mt-8 text-center text-gray-400">購物車是空的</p>
              ) : (
                <ul className="space-y-4">
                  {cart.map((item) => (
                    <li key={item.id} className="flex items-center justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium text-gray-900">{item.name}</p>
                        <p className="text-sm text-gray-500">NT$ {item.price}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => changeQuantity(item.id, -1)}
                          className="flex h-7 w-7 items-center justify-center rounded-full border border-gray-300 text-gray-600 hover:bg-gray-100"
                        >
                          <Minus size={14} />
                        </button>
                        <span className="w-5 text-center">{item.quantity}</span>
                        <button
                          type="button"
                          onClick={() => changeQuantity(item.id, 1)}
                          className="flex h-7 w-7 items-center justify-center rounded-full border border-gray-300 text-gray-600 hover:bg-gray-100"
                        >
                          <Plus size={14} />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="border-t px-5 py-4">
              <div className="mb-3 flex items-center justify-between text-base font-semibold text-gray-900">
                <span>總金額</span>
                <span>NT$ {totalPrice}</span>
              </div>
              <button
                type="button"
                disabled={cart.length === 0}
                onClick={() => {
                  setIsCartOpen(false)
                  navigate('/checkout')
                }}
                className="w-full rounded-full bg-orange-500 py-3 font-medium text-white shadow hover:bg-orange-600 transition-colors disabled:cursor-not-allowed disabled:bg-gray-300"
              >
                前往結帳
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default CustomerMenu
