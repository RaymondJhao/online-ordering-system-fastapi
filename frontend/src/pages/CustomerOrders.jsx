import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { asList, tokenStorage } from "../lib/api";

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

// 綠界的付款結果是伺服器對伺服器通知（ReturnURL），跟「使用者回到這一頁」
// 是兩條獨立的路徑，沒有先後保證。後端在免費方案上閒置會休眠，第一次回調
// 常撞上 30–60 秒的冷啟動而逾時，綠界重送後才會成功——使用者往往比通知先到。
//
// 少了輪詢，畫面會停在「尚未付款」，而使用者沒有理由知道該重新整理。
// 上限刻意設得保守：只在真的有等待中的線上付款訂單時才輪詢，
// 問完就停，不做無止境的背景請求。
const POLL_INTERVAL_MS = 3000
const POLL_MAX_ATTEMPTS = 12

function hasPendingOnlinePayment(orders) {
  return orders.some(
    (order) =>
      order.payment_method === 'ONLINE' &&
      order.payment_status === 'UNPAID' &&
      order.status === 'PENDING',
  )
}

function CustomerOrders() {
  const navigate = useNavigate()
  const [orders, setOrders] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [isWaitingForPayment, setIsWaitingForPayment] = useState(false)

  useEffect(() => {
    const token = tokenStorage.access
    if (!token) {
      navigate('/auth', { state: { from: '/orders' } })
      return undefined
    }

    let attempts = 0
    let timer

    const fetchOrders = () =>
      api
        .get('/api/orders')
        .then((res) => {
          // 後端的 response_model 是 list[OrderResponse]，直接回陣列而非
          // { orders: [...] }。原本只讀 res.data.orders，永遠拿到 undefined，
          // 結果是「請求成功但訂單列表一直是空的」——不會報錯，最難發現的那種。
          const next = asList(res.data)
          setOrders(next)

          const stillWaiting = hasPendingOnlinePayment(next) && attempts < POLL_MAX_ATTEMPTS
          setIsWaitingForPayment(stillWaiting)

          if (stillWaiting) {
            attempts += 1
            timer = setTimeout(fetchOrders, POLL_INTERVAL_MS)
          }
        })
        .catch(() => {
          // 輪詢途中失敗就停下來，不要把畫面上已經顯示的訂單換成錯誤訊息
          setIsWaitingForPayment(false)
          if (attempts === 0) setError('無法取得訂單紀錄，請稍後再試')
        })
        .finally(() => {
          setIsLoading(false)
        })

    fetchOrders()

    return () => clearTimeout(timer)
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

        {isWaitingForPayment && (
          <p className="mb-4 rounded-xl bg-amber-50 px-4 py-3 text-center text-sm text-amber-700">
            正在確認付款結果，這可能需要幾十秒，請稍候（本頁會自動更新）
          </p>
        )}

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

                {order.status === 'REJECTED' && order.reject_reason && (
                  <p className="mt-2 text-sm font-semibold text-red-500">
                    訂單已取消，店家回覆：{order.reject_reason}
                  </p>
                )}

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
