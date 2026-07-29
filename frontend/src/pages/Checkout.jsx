import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api, { tokenStorage } from "../lib/api";
import { extractErrorMessage } from "../lib/errors";
import { useCart } from '../context/CartContext'

function redirectToECPay(paymentUrl, formData) {
  const form = document.createElement('form')
  form.method = 'POST'
  form.action = paymentUrl

  Object.entries(formData).forEach(([key, value]) => {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.name = key
    input.value = value
    form.appendChild(input)
  })

  document.body.appendChild(form)
  form.submit()
}

function Checkout() {
  const { cart, totalPrice, clearCart } = useCart()
  const navigate = useNavigate()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [paymentMethod, setPaymentMethod] = useState('ONLINE')
  const [pickupTime, setPickupTime] = useState('')
  const [couponCode, setCouponCode] = useState('')

  useEffect(() => {
    if (!tokenStorage.access) {
      navigate('/auth', { state: { from: '/checkout' } })
    }
  }, [navigate])

  const handleConfirmPayment = async () => {
    setError(null)

    if (!tokenStorage.access) {
      navigate('/auth', { state: { from: '/checkout' } })
      return
    }
    if (cart.length === 0) {
      setError('購物車是空的')
      return
    }

    setIsSubmitting(true)

    try {
      // Authorization header 由 api 實例的攔截器（src/lib/api.js）自動附加
      const orderRes = await api.post('/api/orders', {
        merchant_id: cart[0].merchant_id,
        items: cart.map((item) => ({
          menu_item_id: item.id,
          quantity: item.quantity,
        })),
        payment_method: paymentMethod,
        pickup_time: pickupTime || undefined,
        coupon_code: couponCode.trim() || undefined,
      })

      const orderId = orderRes.data.order.id

      if (paymentMethod === 'CASH') {
        clearCart()
        alert('訂單建立成功，請至現場付款取餐！')
        navigate('/')
        return
      }

      const paymentRes = await api.post(`/api/payment/checkout/${orderId}`)

      const { payment_url, form_data } = paymentRes.data

      clearCart()
      redirectToECPay(payment_url, form_data)
    } catch (err) {
      setError(extractErrorMessage(err, '建立訂單或付款失敗，請稍後再試'))
      setIsSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="sticky top-0 z-30 bg-white shadow-sm">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3 sm:px-6">
          <h1 className="text-xl font-bold text-gray-900 sm:text-2xl">結帳確認</h1>
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
        {cart.length === 0 ? (
          <p className="py-12 text-center text-gray-400">
            購物車是空的，請先選購餐點
          </p>
        ) : (
          <div className="rounded-2xl bg-white p-5 shadow-md">
            <h2 className="mb-4 text-lg font-bold text-gray-900">訂單明細</h2>

            <ul className="divide-y divide-gray-100">
              {cart.map((item) => (
                <li
                  key={item.id}
                  className="flex items-center justify-between py-3"
                >
                  <div>
                    <p className="font-medium text-gray-900">{item.name}</p>
                    <p className="text-sm text-gray-500">
                      NT$ {item.price} x {item.quantity}
                    </p>
                  </div>
                  <span className="font-semibold text-gray-900">
                    NT$ {item.price * item.quantity}
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-4 flex items-center justify-between border-t pt-4 text-lg font-bold text-gray-900">
              <span>總金額</span>
              <span>NT$ {totalPrice}</span>
            </div>

            <div className="mt-6 border-t pt-4">
              <h2 className="mb-3 text-sm font-semibold text-gray-700">預約取餐時間</h2>
              <input
                type="datetime-local"
                value={pickupTime}
                onChange={(e) => setPickupTime(e.target.value)}
                className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm text-gray-900 focus:border-orange-500 focus:outline-none focus:ring-1 focus:ring-orange-500"
              />
              <p className="mt-1 text-xs text-gray-400">
                不填寫則預設盡快為您準備餐點
              </p>
            </div>

            <div className="mt-6 border-t pt-4">
              <h2 className="mb-3 text-sm font-semibold text-gray-700">優惠券</h2>
              <input
                type="text"
                value={couponCode}
                onChange={(e) => setCouponCode(e.target.value)}
                placeholder="輸入優惠碼"
                className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-orange-500 focus:outline-none focus:ring-1 focus:ring-orange-500"
              />
            </div>

            <div className="mt-6 border-t pt-4">
              <h2 className="mb-3 text-sm font-semibold text-gray-700">付款方式</h2>
              <div className="flex gap-3">
                <label
                  className={`flex flex-1 cursor-pointer items-center justify-center rounded-xl border px-4 py-3 text-sm font-medium transition-colors ${
                    paymentMethod === 'ONLINE'
                      ? 'border-orange-500 bg-orange-50 text-orange-600'
                      : 'border-gray-300 text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="radio"
                    name="payment_method"
                    value="ONLINE"
                    checked={paymentMethod === 'ONLINE'}
                    onChange={() => setPaymentMethod('ONLINE')}
                    className="sr-only"
                  />
                  線上刷卡
                </label>
                <label
                  className={`flex flex-1 cursor-pointer items-center justify-center rounded-xl border px-4 py-3 text-sm font-medium transition-colors ${
                    paymentMethod === 'CASH'
                      ? 'border-orange-500 bg-orange-50 text-orange-600'
                      : 'border-gray-300 text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  <input
                    type="radio"
                    name="payment_method"
                    value="CASH"
                    checked={paymentMethod === 'CASH'}
                    onChange={() => setPaymentMethod('CASH')}
                    className="sr-only"
                  />
                  現場現金
                </label>
              </div>
            </div>

            {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

            <button
              type="button"
              onClick={handleConfirmPayment}
              disabled={isSubmitting}
              className="mt-6 w-full rounded-full bg-orange-500 py-3 font-medium text-white shadow hover:bg-orange-600 transition-colors disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {isSubmitting
                ? '處理中...'
                : paymentMethod === 'CASH'
                  ? '確認建立訂單'
                  : '確認付款'}
            </button>
          </div>
        )}
      </main>
    </div>
  )
}

export default Checkout
