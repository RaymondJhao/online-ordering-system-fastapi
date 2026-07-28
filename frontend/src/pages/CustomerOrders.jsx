import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

const STATUS_LABELS = {
  PENDING: '待商家確認',
  ACCEPTED: '已接單',
  PREPARING: '製作中',
  READY: '待取餐',
  COMPLETED: '已完成',
  REJECTED: '已拒絕',
  CANCELLED: '已取消',
  REFUNDED: '已退款',
}

const STATUS_STYLES = {
  PENDING: 'bg-amber-50 text-amber-600',
  ACCEPTED: 'bg-blue-50 text-blue-600',
  PREPARING: 'bg-blue-50 text-blue-600',
  READY: 'bg-emerald-50 text-emerald-600',
  COMPLETED: 'bg-gray-100 text-gray-600',
  REJECTED: 'bg-red-50 text-red-600',
  CANCELLED: 'bg-red-50 text-red-600',
  REFUNDED: 'bg-red-50 text-red-600',
}

function formatDateTime(value) {
  if (!value) return '未指定'
  return new Date(value).toLocaleString('zh-TW', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function CustomerOrders() {
  const navigate = useNavigate()
  const [orders, setOrders] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) {
      navigate('/auth', { state: { from: '/orders' } })
      return
    }

    axios
      .get('/api/orders')
      .then((res) => {
        setOrders(res.data.orders ?? [])
      })
      .catch(() => {
        setError('無法取得訂單紀錄，請稍後再試')
      })
      .finally(() => {
        setIsLoading(false)
      })
  }, [navigate])

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="sticky top-0 z-30 bg-white shadow-sm">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3 sm:px-6">
          <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">我的訂單</h1>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="text-sm text-gray-500 hover:text-gray-700"
          >
            返回菜單
          </button>
        </div>
      </nav>

      <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6">
        {isLoading && (
          <p className="py-12 text-center text-gray-500">訂單載入中...</p>
        )}

        {error && <p className="py-12 text-center text-red-500">{error}</p>}

        {!isLoading && !error && orders.length === 0 && (
          <p className="py-12 text-center text-gray-400">目前沒有任何訂單紀錄</p>
        )}

        {!isLoading && !error && orders.length > 0 && (
          <ul className="space-y-4">
            {orders.map((order) => (
              <li
                key={order.id}
                className="rounded-2xl bg-white p-5 shadow-md"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-base font-bold text-gray-900">
                      訂單編號 #{order.id}
                    </p>
                    <p className="mt-1 text-sm text-gray-500">
                      建立時間：{formatDateTime(order.created_at)}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${
                      STATUS_STYLES[order.status] ?? 'bg-gray-100 text-gray-600'
                    }`}
                  >
                    {STATUS_LABELS[order.status] ?? order.status}
                  </span>
                </div>

                <ul className="mt-4 divide-y divide-gray-100 border-y border-gray-100">
                  {order.items.map((item) => (
                    <li
                      key={item.menu_item_id}
                      className="flex items-center justify-between py-2 text-sm"
                    >
                      <span className="text-gray-700">
                        {item.name} x {item.quantity}
                      </span>
                      <span className="text-gray-500">
                        NT$ {item.price * item.quantity}
                      </span>
                    </li>
                  ))}
                </ul>

                <div className="mt-4 space-y-1 text-sm">
                  <div className="flex items-center justify-between text-gray-600">
                    <span>取餐時間</span>
                    <span>{formatDateTime(order.pickup_time)}</span>
                  </div>
                  {order.discount_amount > 0 && (
                    <div className="flex items-center justify-between text-orange-600">
                      <span>折抵金額</span>
                      <span>- NT$ {order.discount_amount}</span>
                    </div>
                  )}
                  <div className="flex items-center justify-between pt-1 text-base font-bold text-gray-900">
                    <span>總金額</span>
                    <span>NT$ {order.total_price}</span>
                  </div>
                </div>

                {order.status === 'PENDING' && (
                  <p className="mt-4 text-sm font-medium text-red-500">
                    如需取消訂單，請來電門市處理
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  )
}

export default CustomerOrders
