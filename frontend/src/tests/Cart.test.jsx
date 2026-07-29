import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { CartProvider, useCart } from '../context/CartContext'

const CART_STORAGE_KEY = 'shopping_cart'

const burger = { id: 1, name: '招牌漢堡', price: 120 }
const fries = { id: 2, name: '薯條', price: 60 }

function TestCartConsumer() {
  const { cart, addToCart, totalCount, totalPrice } = useCart()
  return (
    <div>
      <button onClick={() => addToCart(burger)}>加入購物車：招牌漢堡</button>
      <button onClick={() => addToCart(fries)}>加入購物車：薯條</button>
      <p data-testid="cart-length">{cart.length}</p>
      <p data-testid="total-count">{totalCount}</p>
      <p data-testid="total-price">{totalPrice}</p>
    </div>
  )
}

function renderCart() {
  return render(
    <CartProvider>
      <TestCartConsumer />
    </CartProvider>
  )
}

describe('購物車邏輯 (CartContext)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('點擊「加入購物車」後，購物車陣列長度增加且畫面上的總金額計算正確', () => {
    renderCart()

    fireEvent.click(screen.getByText('加入購物車：招牌漢堡'))
    fireEvent.click(screen.getByText('加入購物車：薯條'))

    expect(screen.getByTestId('cart-length')).toHaveTextContent('2')
    // 120 (漢堡) + 60 (薯條) = 180
    expect(screen.getByTestId('total-price')).toHaveTextContent('180')
  })

  it('購物車狀態變更後會成功寫入 localStorage 以達成持久化', () => {
    renderCart()

    fireEvent.click(screen.getByText('加入購物車：招牌漢堡'))
    fireEvent.click(screen.getByText('加入購物車：招牌漢堡'))

    const stored = JSON.parse(localStorage.getItem(CART_STORAGE_KEY))
    expect(stored).toHaveLength(1)
    expect(stored[0]).toMatchObject({ id: burger.id, quantity: 2 })
  })
})
