import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
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

  const handleConfirmPayment = async () => {
    setError(null)

    const token = localStorage.getItem('token')
    if (!token) {
      setError('請先登入後再進行付款')
      return
    }
    if (cart.length === 0) {
      setError('購物車是空的')
      return
    }

    setIsSubmitting(true)

    try {
      const authHeader = { Authorization: `Bearer ${token}` }

      const orderRes = await axios.post(
        '/api/orders',
        {
          merchant_id: cart[0].merchant_id,
          items: cart.map((item) => ({
            menu_item_id: item.id,
            quantity: item.quantity,
          })),
        },
        { headers: authHeader }
      )

      const orderId = orderRes.data.order.id

      const paymentRes = await axios.post(
        `/api/payment/checkout/${orderId}`,
        {},
        { headers: authHeader }
      )

      const { payment_url, form_data } = paymentRes.data

      clearCart()
      redirectToECPay(payment_url, form_data)
    } catch (err) {
      setError(err.response?.data?.message ?? '建立訂單或付款失敗，請稍後再試')
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

            {error && <p className="mt-4 text-sm text-red-500">{error}</p>}

            <button
              type="button"
              onClick={handleConfirmPayment}
              disabled={isSubmitting}
              className="mt-6 w-full rounded-full bg-orange-500 py-3 font-medium text-white shadow hover:bg-orange-600 transition-colors disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              {isSubmitting ? '處理中...' : '確認付款'}
            </button>
          </div>
        )}
      </main>
    </div>
  )
}

export default Checkout
